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
