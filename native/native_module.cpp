// Experimental native filter kernel for qpy-rsync.
// The Python side owns the GUI and the Qt model; this module owns only flat
// arrays and returns compact index buffers, so nothing O(n) crosses the
// boundary on a hot call.

#include <nanobind/nanobind.h>
#include <nanobind/stl/bind_vector.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/tuple.h>
#include <nanobind/stl/vector.h>

#include <cstdint>
#include <string>
#include <vector>

namespace nb = nanobind;

using u32 = std::uint32_t;
using i64 = std::int64_t;
using u8 = std::uint8_t;

struct NativeFilter {
  std::vector<u32> change_index;
  std::vector<u32> dir_index;
  std::vector<u32> is_dir;
  std::vector<i64> sizes;
  std::size_t dir_count = 0;

  NativeFilter(std::vector<int> change_index_, std::vector<int> dir_index_,
               std::vector<bool> is_dir_, std::vector<i64> sizes_,
               std::size_t dir_count_)
      : change_index(change_index_.begin(), change_index_.end()),
        dir_index(dir_index_.begin(), dir_index_.end()),
        is_dir(is_dir_.begin(), is_dir_.end()),
        sizes(std::move(sizes_)), dir_count(dir_count_) {}

  // Returns (visible rows, visible change indices, per-directory count,size).
  std::tuple<std::vector<u32>, std::vector<u32>,
             std::vector<std::tuple<u32, i64>>>
  apply(const std::vector<bool>& change_visible,
        const std::vector<bool>& dir_visible,
        const std::vector<bool>& excluded, bool show_excluded,
        const std::vector<bool>& folded_parent) const {
    std::vector<u32> rows;
    std::vector<u32> changes;
    std::vector<u32> counts(dir_count, 0);
    std::vector<i64> totals(dir_count, 0);
    rows.reserve(change_index.size());
    changes.reserve(change_index.size());

    for (std::size_t i = 0; i < change_index.size(); ++i) {
      const bool is_excluded = i < excluded.size() && excluded[i];
      if (is_excluded && !show_excluded) continue;
      if (!folded_parent.empty() && folded_parent[i]) continue;
      if (is_dir[i]) {
        if (i < dir_visible.size() && !dir_visible[i] && !is_excluded) continue;
      } else {
        if (i < change_visible.size() && !change_visible[i] && !is_excluded)
          continue;
      }
      rows.push_back(static_cast<u32>(i));
      const u32 ci = change_index[i];
      if (is_dir[i] || !is_excluded) {
        if (ci != 0 || is_dir[i]) changes.push_back(ci);
      }
      const u32 di = dir_index[i];
      if (di < dir_count) {
        ++counts[di];
        totals[di] += sizes[i];
      }
    }
    std::vector<std::tuple<u32, i64>> aggregates;
    aggregates.reserve(dir_count);
    for (std::size_t i = 0; i < dir_count; ++i)
      aggregates.emplace_back(counts[i], totals[i]);
    return {std::move(rows), std::move(changes), std::move(aggregates)};
  }
};

// Persistent native mirror of one comparison. This owns the flat row arrays
// so a filter pass takes only small flag buffers and returns row positions.
// It deliberately mirrors the final row loop of FlatChangeModel._apply_filters:
// the per-change and per-directory flag computation is still done by Python in
// this first stage (see docs/native-backend-plan.md).
struct NativeComparison {
  static constexpr u32 NO_INDEX = 0xFFFFFFFFu;

  // Immutable layout, supplied once at construction.
  std::vector<std::string> paths;
  std::vector<std::string> folded_names;
  std::vector<std::string> folded_paths;
  std::vector<u32> change_index;   // row -> change (NO_INDEX for a plain folder)
  std::vector<u32> dir_index;      // row -> owning folder index
  std::vector<u32> own_dir_index;  // dir row -> its own folder index (aggregate)
  std::vector<u32> is_dir;
  std::vector<i64> change_sizes;   // indexed by change, not by row

  // Outputs, reused between passes.
  std::vector<u32> visible_rows;
  std::vector<u32> visible_changes;
  std::vector<u32> dir_counts;
  std::vector<i64> dir_sizes;

  NativeComparison(std::vector<std::string> paths_,
                   std::vector<std::string> folded_names_,
                   std::vector<std::string> folded_paths_,
                   std::vector<int> change_index_, std::vector<int> dir_index_,
                   std::vector<int> own_dir_index_, std::vector<bool> is_dir_,
                   std::vector<i64> change_sizes_)
      : paths(std::move(paths_)), folded_names(std::move(folded_names_)),
        folded_paths(std::move(folded_paths_)),
        change_index(change_index_.begin(), change_index_.end()),
        dir_index(dir_index_.begin(), dir_index_.end()),
        own_dir_index(own_dir_index_.begin(), own_dir_index_.end()),
        is_dir(is_dir_.begin(), is_dir_.end()),
        change_sizes(std::move(change_sizes_)),
        dir_counts(paths.size() ? 0 : 0) {
    // Size the aggregate arrays to cover every folder that can own a row.
    std::size_t max_dir = 0;
    for (u32 value : dir_index) {
      if (value != NO_INDEX && value + 1u > max_dir) max_dir = value + 1u;
    }
    for (u32 value : own_dir_index) {
      if (value != NO_INDEX && value + 1u > max_dir) max_dir = value + 1u;
    }
    dir_counts.assign(max_dir, 0);
    dir_sizes.assign(max_dir, 0);
  }

  std::size_t row_count() const { return paths.size(); }
  std::size_t dir_count() const { return dir_counts.size(); }
  const std::vector<u32>& rows() const { return visible_rows; }
  const std::vector<u32>& changes() const { return visible_changes; }
  const std::vector<u32>& counts() const { return dir_counts; }
  const std::vector<i64>& sizes_per_dir() const { return dir_sizes; }

  // Recompute visibility and aggregates from per-row flags. Each flag buffer
  // is indexed by row position. Returns a generation counter so a caller can
  // discard a stale worker result.
  u32 apply(const std::vector<u8>& row_visible,
            const std::vector<u8>& row_path_ok,
            const std::vector<u8>& row_faded,
            const std::vector<u8>& row_excluded,
            const std::vector<u8>& row_explicit,
            const std::vector<u8>& folded_parent, bool has_exclusion,
            bool show_excluded, u32 generation) {
    visible_rows.clear();
    visible_changes.clear();
    std::fill(dir_counts.begin(), dir_counts.end(), 0);
    std::fill(dir_sizes.begin(), dir_sizes.end(), 0);
    visible_rows.reserve(paths.size());
    visible_changes.reserve(paths.size() / 2);
    const bool check_excluded = has_exclusion && !show_excluded;

    for (std::size_t i = 0; i < paths.size(); ++i) {
      const bool inherited =
          has_exclusion && i < row_excluded.size() && row_excluded[i] != 0;
      const bool explicit_excluded =
          has_exclusion && i < row_explicit.size() && row_explicit[i] != 0;
      const bool faded = i < row_faded.size() && row_faded[i] != 0;
      const bool path_ok =
          i < row_path_ok.size() && row_path_ok[i] != 0;
      const bool visible = i < row_visible.size() && row_visible[i] != 0;
      const u32 ci = i < change_index.size() ? change_index[i] : NO_INDEX;
      u32 di = i < dir_index.size() ? dir_index[i] : 0;

      if (is_dir[i]) {
        // Mirror FlatChangeModel: an inherited exclusion keeps the folder
        // when show_excluded is on and path_ok holds; otherwise the folder's
        // own visibility flag decides. The explicit value only affects the
        // row's drawn state, not its presence.
        if (!inherited) {
          if (!visible) continue;
        } else if (check_excluded || !path_ok) {
          continue;
        }
        if (ci != NO_INDEX && !inherited && !faded) {
          visible_changes.push_back(ci);
          di = i < own_dir_index.size() ? own_dir_index[i] : di;
          if (di < dir_counts.size()) {
            ++dir_counts[di];
            dir_sizes[di] += ci < change_sizes.size() ? change_sizes[ci] : 0;
          }
        }
      } else {
        if (inherited) {
          if (check_excluded || !path_ok) continue;
        } else if (!visible) {
          continue;
        }
        if (!inherited && ci != NO_INDEX) {
          visible_changes.push_back(ci);
          if (di < dir_counts.size()) {
            ++dir_counts[di];
            dir_sizes[di] += ci < change_sizes.size() ? change_sizes[ci] : 0;
          }
        }
      }

      // Folded rows still contribute to aggregates and the change set; they
      // are only removed from the list the view paints.
      if (!folded_parent.empty() && i < folded_parent.size() &&
          folded_parent[i]) {
        continue;
      }
      visible_rows.push_back(static_cast<u32>(i));
    }
    return generation + 1;
  }
};

// Experimental rsync itemized-record parser. Mirrors backend/rsync_parser.py
// closely enough to measure the raw parse cost without Python object creation.
struct ParsedRecords {
  std::vector<std::string> paths;
  std::vector<int> actions;
  std::vector<int> kinds;
  std::vector<i64> sizes;
  std::vector<std::string> codes;
  std::vector<std::string> times;
};

static ParsedRecords parse_records_native(const std::string& input,
                                          bool delete_enabled) {
  static const std::string sep = "|qpy-rsync|";
  ParsedRecords out;
  std::size_t cursor = 0;
  while (cursor <= input.size()) {
    std::size_t end = input.find('\n', cursor);
    if (end == std::string::npos) end = input.size();
    std::string line = input.substr(cursor, end - cursor);
    cursor = end + 1;
    if (!line.empty() && line.back() == '\r') line.pop_back();
    if (line.empty()) continue;
    std::size_t a = line.find(sep);
    if (a == std::string::npos) continue;
    std::size_t b = line.find(sep, a + sep.size());
    if (b == std::string::npos) continue;
    std::size_t c = line.find(sep, b + sep.size());
    if (c == std::string::npos) continue;
    const std::string code = line.substr(0, a);
    const std::string size_text = line.substr(a + sep.size(), b - a - sep.size());
    const std::string time_text = line.substr(b + sep.size(), c - b - sep.size());
    std::string path = line.substr(c + sep.size());
    const bool deleting = code.rfind("*deleting", 0) == 0;
    if (!deleting && code.size() != 11) continue;
    static const std::string link_marker = " -> ";
    if (!deleting && code.size() > 1 && code[1] == 'L') {
      std::size_t marker = path.find(link_marker);
      if (marker != std::string::npos) path = path.substr(0, marker);
    }
    if (path == "." || path == "./") continue;
    if (path.empty()) continue;
    int action = 0;  // create
    if (deleting) {
      action = delete_enabled ? 4 : 5;  // delete / destination_only
    } else {
      const std::string attrs = code.substr(2);
      if (attrs.find('+') != std::string::npos) {
        action = 0;
      } else if (code[0] == '>' || code[0] == '<' || code[0] == 'c' ||
                 code[0] == 'h') {
        action = 1;  // update content
      } else {
        bool metadata = false;
        for (char ch : attrs) {
          if (ch != '.' && ch != ' ') metadata = true;
        }
        action = metadata ? 2 : 6;  // metadata / no_change
      }
    }
    int kind = 0;  // file
    if (deleting) {
      kind = (!path.empty() && path.back() == '/') ? 1 : 0;
    } else if (code.size() > 1) {
      switch (code[1]) {
        case 'd': kind = 1; break;
        case 'L': kind = 2; break;
        case 'D': kind = 3; break;
        case 'S': kind = 4; break;
        default: kind = 0;
      }
    }
    i64 size = 0;
    if (!deleting) {
      std::size_t pos = 0;
      if (!size_text.empty()) {
        try {
          size = std::stoll(size_text, &pos);
          if (pos != size_text.size()) size = 0;
        } catch (...) {
          size = 0;
        }
      }
    }
    out.paths.push_back(std::move(path));
    out.actions.push_back(action);
    out.kinds.push_back(kind);
    out.sizes.push_back(size);
    out.codes.push_back(code);
    out.times.push_back(deleting ? std::string() : time_text);
    if (end == input.size()) break;
  }
  return out;
}

NB_MODULE(_qpy_native, m) {
  nb::class_<NativeFilter>(m, "NativeFilter")
      .def(nb::init<std::vector<int>, std::vector<int>, std::vector<bool>,
                    std::vector<i64>, std::size_t>())
      .def("apply", &NativeFilter::apply);
  nb::class_<NativeComparison>(m, "NativeComparison")
      .def(nb::init<std::vector<std::string>, std::vector<std::string>,
                    std::vector<std::string>, std::vector<int>,
                    std::vector<int>, std::vector<int>, std::vector<bool>,
                    std::vector<i64>>())
      .def("row_count", &NativeComparison::row_count)
      .def("dir_count", &NativeComparison::dir_count)
      .def("apply", &NativeComparison::apply, nb::arg("row_visible"),
           nb::arg("row_path_ok"), nb::arg("row_faded"),
           nb::arg("row_excluded"), nb::arg("row_explicit"),
           nb::arg("folded_parent"), nb::arg("has_exclusion"),
           nb::arg("show_excluded"), nb::arg("generation"))
      .def_ro("visible_rows", &NativeComparison::visible_rows)
      .def_ro("visible_changes", &NativeComparison::visible_changes)
      .def_ro("dir_counts", &NativeComparison::dir_counts)
      .def_ro("dir_sizes", &NativeComparison::dir_sizes);
  nb::class_<ParsedRecords>(m, "ParsedRecords")
      .def_ro("paths", &ParsedRecords::paths)
      .def_ro("actions", &ParsedRecords::actions)
      .def_ro("kinds", &ParsedRecords::kinds)
      .def_ro("sizes", &ParsedRecords::sizes)
      .def_ro("codes", &ParsedRecords::codes)
      .def_ro("times", &ParsedRecords::times);
  m.def("parse_records", &parse_records_native, nb::arg("input"),
        nb::arg("delete_enabled"));
}
