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
using u64 = std::uint64_t;
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

// A small fnmatch-compatible matcher over casefolded UTF-8 bytes. It supports
// the syntax FlatChangeModel documents: '*', '?', '[seq]', '[!seq]' and ranges.
static bool glob_match(const std::string& text, const std::string& pattern) {
  std::size_t t = 0;
  std::size_t p = 0;
  std::size_t star = std::string::npos;
  std::size_t star_text = 0;
  while (t < text.size()) {
    if (p < pattern.size() && (pattern[p] == '?' || pattern[p] == text[t])) {
      ++p;
      ++t;
      continue;
    }
    if (p < pattern.size() && pattern[p] == '[') {
      std::size_t end = p + 1;
      bool negate = false;
      if (end < pattern.size() && (pattern[end] == '!' || pattern[end] == '^')) {
        negate = true;
        ++end;
      }
      bool matched = false;
      bool first = true;
      while (end < pattern.size() && (pattern[end] != ']' || first)) {
        first = false;
        if (end + 2 < pattern.size() && pattern[end + 1] == '-' &&
            pattern[end + 2] != ']') {
          if (text[t] >= pattern[end] && text[t] <= pattern[end + 2]) {
            matched = true;
          }
          end += 3;
        } else {
          if (text[t] == pattern[end]) matched = true;
          ++end;
        }
      }
      if (end < pattern.size() && matched != negate) {
        p = end + 1;
        ++t;
        continue;
      }
    }
    if (p < pattern.size() && pattern[p] == '*') {
      star = p++;
      star_text = t;
      continue;
    }
    if (star != std::string::npos) {
      p = star + 1;
      t = ++star_text;
      continue;
    }
    return false;
  }
  while (p < pattern.size() && pattern[p] == '*') ++p;
  return p == pattern.size();
}

static bool folded_matches(const std::string& folded_name,
                           const std::string& folded_path, bool is_dir,
                           const std::string& pattern, bool pattern_is_glob,
                           bool directories_only) {
  if (directories_only && !is_dir) return false;
  if (directories_only && is_dir && !pattern_is_glob) {
    if (pattern.find('/') != std::string::npos) return folded_path == pattern;
    return folded_name == pattern;
  }
  const std::string& candidate =
      pattern.find('/') != std::string::npos ? folded_path : folded_name;
  if (pattern_is_glob) return glob_match(candidate, pattern);
  return candidate.find(pattern) != std::string::npos;
}

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
  std::vector<i64> change_dest_sizes;

  // Outputs, reused between passes.
  std::vector<u32> visible_rows;
  std::vector<u32> visible_changes;
  std::vector<u32> dir_counts;
  std::vector<i64> dir_sizes;
  // count, size, destination size, source items, destination items
  std::vector<i64> dir_totals;

  NativeComparison(std::vector<std::string> paths_,
                   std::vector<std::string> folded_names_,
                   std::vector<std::string> folded_paths_,
                   std::vector<int> change_index_, std::vector<int> dir_index_,
                   std::vector<int> own_dir_index_, std::vector<bool> is_dir_,
                   std::vector<i64> change_sizes_,
                   std::vector<i64> change_dest_sizes_)
      : paths(std::move(paths_)), folded_names(std::move(folded_names_)),
        folded_paths(std::move(folded_paths_)),
        change_index(change_index_.begin(), change_index_.end()),
        dir_index(dir_index_.begin(), dir_index_.end()),
        own_dir_index(own_dir_index_.begin(), own_dir_index_.end()),
        is_dir(is_dir_.begin(), is_dir_.end()),
        change_sizes(std::move(change_sizes_)),
        change_dest_sizes(std::move(change_dest_sizes_)) {
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
    dir_totals.assign(max_dir * 5, 0);
  }

  std::size_t row_count() const { return paths.size(); }
  std::size_t dir_count() const { return dir_counts.size(); }
  const std::vector<u32>& rows() const { return visible_rows; }
  const std::vector<u32>& changes() const { return visible_changes; }
  const std::vector<u32>& counts() const { return dir_counts; }
  const std::vector<i64>& sizes_per_dir() const { return dir_sizes; }
  const std::vector<i64>& totals_per_dir() const { return dir_totals; }

  // Shared row loop. Mirrors the final pass of FlatChangeModel._apply_filters:
  // visibility, the visible change set and the per-directory aggregates.
  u32 emit(const std::vector<u8>& row_visible,
           const std::vector<u8>& row_path_ok,
           const std::vector<u8>& row_faded,
           const std::vector<u8>& row_excluded,
           const std::vector<u8>& row_explicit, bool has_exclusion,
           bool show_excluded, const std::vector<u8>& folded_parent,
           u32 generation) {
    visible_rows.clear();
    visible_changes.clear();
    std::fill(dir_counts.begin(), dir_counts.end(), 0);
    std::fill(dir_sizes.begin(), dir_sizes.end(), 0);
    std::fill(dir_totals.begin(), dir_totals.end(), 0);
    visible_rows.reserve(paths.size());
    visible_changes.reserve(paths.size() / 2);
    const bool check_excluded = has_exclusion && !show_excluded;

    for (std::size_t i = 0; i < paths.size(); ++i) {
      const bool inherited =
          has_exclusion && i < row_excluded.size() && row_excluded[i] != 0;
      const bool explicit_excluded =
          has_exclusion && i < row_explicit.size() && row_explicit[i] != 0;
      const bool faded = i < row_faded.size() && row_faded[i] != 0;
      const bool path_ok = i < row_path_ok.size() && row_path_ok[i] != 0;
      const bool visible = i < row_visible.size() && row_visible[i] != 0;
      const u32 ci = i < change_index.size() ? change_index[i] : NO_INDEX;
      u32 di = i < dir_index.size() ? dir_index[i] : 0;

      if (is_dir[i]) {
        // An inherited exclusion keeps the folder when show_excluded is on
        // and path_ok holds; otherwise the folder's own visibility decides.
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
            const i64 size = ci < change_sizes.size() ? change_sizes[ci] : 0;
            ++dir_counts[di];
            dir_sizes[di] += size;
            if (!explicit_excluded && !change_action.empty() &&
                !change_dest_sizes.empty() && di * 5 + 4 < dir_totals.size()) {
              const u32 code = ci < change_action.size() ? change_action[ci] : 0;
              i64* totals = &dir_totals[di * 5];
              totals[0] += 1;
              totals[1] += size;
              totals[2] += ci < change_dest_sizes.size() ? change_dest_sizes[ci] : 0;
              totals[3] += code != 4 ? 1 : 0;  // not DESTINATION_ONLY
              totals[4] += code != 0 ? 1 : 0;  // not CREATE
            }
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

  // Stage 1 API: every per-row flag is supplied by Python. The row_explicit
  // buffer is accepted for compatibility; row presence never depends on it,
  // matching FlatChangeModel.
  u32 apply(const std::vector<u8>& row_visible,
            const std::vector<u8>& row_path_ok,
            const std::vector<u8>& row_faded,
            const std::vector<u8>& row_excluded,
            const std::vector<u8>& row_explicit,
            const std::vector<u8>& folded_parent, bool has_exclusion,
            bool show_excluded, u32 generation) {
    return emit(row_visible, row_path_ok, row_faded, row_excluded, row_explicit,
                has_exclusion, show_excluded, folded_parent, generation);
  }

  // ---- Stage 2: native computation of the change and directory flags ----
  std::vector<u32> change_dir;        // per change -> owning directory
  std::vector<u32> change_action;     // per change -> effective action code
  std::vector<u32> dir_parent;        // per directory -> parent (NO_INDEX root)
  std::vector<u32> dir_own_change;    // per directory -> own change (NO_INDEX)
  std::vector<u32> dir_child_offsets; // CSR over dir_child_indices
  std::vector<u32> dir_child_indices;
  std::vector<u32> dir_file_offsets;  // CSR over dir_file_indices
  std::vector<u32> dir_file_indices;
  std::vector<u32> dir_order;         // children before parents, root excluded
  std::vector<u32> dir_row;           // directory index -> a representative row
  std::vector<u32> row_of_change;     // change index -> its row

  std::vector<u8> change_visible;
  std::vector<u8> change_action_ok;
  std::vector<u8> change_path_ok;
  std::vector<u8> dir_path_ok;
  std::vector<u8> dir_action_ok;
  std::vector<u8> dir_faded;
  std::vector<u8> dir_visible;

  // Refresh only the effective action codes after a decision change. The
  // hierarchy (CSR arrays) does not change, so this is cheaper than rebuilding
  // the whole structure.
  void set_actions(const std::vector<int>& actions) {
    change_action.assign(actions.begin(), actions.end());
  }

  void set_action_filter(u32 mask) {
    actions_mask_ = mask;
    actions_mask_active_ = mask != 0;
  }

  void set_filter_directories(bool enabled) { filter_directories_ = enabled; }

  void set_structure(std::vector<int> change_dir_,
                     std::vector<bool> change_is_dir_,
                     std::vector<int> change_action_,
                     std::vector<int> dir_parent_,
                     std::vector<int> dir_own_change_) {
    change_dir.assign(change_dir_.begin(), change_dir_.end());
    change_action.assign(change_action_.begin(), change_action_.end());
    dir_parent.assign(dir_parent_.begin(), dir_parent_.end());
    dir_own_change.assign(dir_own_change_.begin(), dir_own_change_.end());
    const std::size_t ndirs = dir_parent.size();
    const std::size_t nchanges = change_dir.size();

    std::vector<u32> child_counts(ndirs, 0);
    std::vector<u32> file_counts(ndirs, 0);
    for (std::size_t ci = 0; ci < nchanges; ++ci) {
      const u32 di = change_dir[ci];
      if (di == NO_INDEX || di >= ndirs) continue;
      if (ci < change_is_dir_.size() && change_is_dir_[ci]) continue;
      ++file_counts[di];
    }
    for (std::size_t di = 1; di < ndirs; ++di) {
      const u32 parent = dir_parent[di];
      if (parent != NO_INDEX && parent < ndirs) ++child_counts[parent];
    }
    dir_child_offsets.assign(ndirs + 1, 0);
    dir_file_offsets.assign(ndirs + 1, 0);
    for (std::size_t di = 0; di < ndirs; ++di) {
      dir_child_offsets[di + 1] = dir_child_offsets[di] + child_counts[di];
      dir_file_offsets[di + 1] = dir_file_offsets[di] + file_counts[di];
    }
    dir_child_indices.assign(dir_child_offsets[ndirs], 0);
    dir_file_indices.assign(dir_file_offsets[ndirs], 0);
    std::vector<u32> child_cursor(dir_child_offsets.begin(),
                                  dir_child_offsets.end());
    std::vector<u32> file_cursor(dir_file_offsets.begin(),
                                 dir_file_offsets.end());
    for (std::size_t ci = 0; ci < nchanges; ++ci) {
      const u32 di = change_dir[ci];
      if (di == NO_INDEX || di >= ndirs) continue;
      if (ci < change_is_dir_.size() && change_is_dir_[ci]) continue;
      dir_file_indices[file_cursor[di]++] = static_cast<u32>(ci);
    }
    for (std::size_t di = 1; di < ndirs; ++di) {
      const u32 parent = dir_parent[di];
      if (parent != NO_INDEX && parent < ndirs) {
        dir_child_indices[child_cursor[parent]++] = static_cast<u32>(di);
      }
    }
    dir_row.assign(ndirs, NO_INDEX);
    row_of_change.assign(nchanges, NO_INDEX);
    for (std::size_t i = 0; i < paths.size(); ++i) {
      const u32 ci = i < change_index.size() ? change_index[i] : NO_INDEX;
      if (ci != NO_INDEX && ci < row_of_change.size()) {
        row_of_change[ci] = static_cast<u32>(i);
      }
      if (is_dir[i]) {
        const u32 di = i < own_dir_index.size() ? own_dir_index[i] : NO_INDEX;
        if (di != NO_INDEX && di < dir_row.size()) {
          dir_row[di] = static_cast<u32>(i);
        }
      }
    }
    // Reverse insertion order puts every child before its parent.
    dir_order.clear();
    for (std::size_t di = ndirs; di-- > 1;) {
      dir_order.push_back(static_cast<u32>(di));
    }

    change_visible.assign(nchanges, 0);
    change_action_ok.assign(nchanges, 0);
    change_path_ok.assign(nchanges, 0);
    dir_path_ok.assign(ndirs, 0);
    dir_action_ok.assign(ndirs, 0);
    dir_faded.assign(ndirs, 0);
    dir_visible.assign(ndirs, 0);
  }


  std::vector<u32> search_rows(const std::string& pattern, bool is_glob,
                               bool directories_only, bool show_excluded,
                               const std::vector<u8>& row_excluded) const {
    std::vector<u32> matches;
    matches.reserve(paths.size() / 8);
    for (std::size_t i = 0; i < paths.size(); ++i) {
      if (!show_excluded && i < row_excluded.size() && row_excluded[i]) {
        continue;
      }
      if (folded_matches(
              i < folded_names.size() ? folded_names[i] : std::string(),
              i < folded_paths.size() ? folded_paths[i] : std::string(),
              i < is_dir.size() && is_dir[i] != 0, pattern, is_glob,
              directories_only)) {
        matches.push_back(static_cast<u32>(i));
      }
    }
    return matches;
  }

  u32 actions_mask_ = 0;
  bool actions_mask_active_ = false;
  bool filter_directories_ = false;

  // actions_mask == 0 means "no action filter". Otherwise bit N keeps changes
  // whose effective action code is N. This replaces the Python change loop
  // and the directory closure for comparisons without a path pattern.
  u32 filter(u32 actions_mask, bool filter_directories, bool has_exclusion,
             const std::vector<u8>& row_excluded,
             const std::vector<u8>& row_explicit, bool show_excluded,
             const std::vector<u8>& folded_parent, u32 generation) {
    actions_mask_ = actions_mask;
    actions_mask_active_ = actions_mask != 0;
    filter_directories_ = filter_directories;
    const std::size_t nchanges = change_dir.size();
    for (std::size_t ci = 0; ci < nchanges; ++ci) {
      const u32 code = ci < change_action.size() ? change_action[ci] : 0;
      const bool keep = actions_mask == 0 ||
                        (code < 32 && ((actions_mask >> code) & 1u) != 0);
      change_visible[ci] = keep ? 1 : 0;
      change_action_ok[ci] = keep ? 1 : 0;
      change_path_ok[ci] = 1;  // no path pattern in this stage
    }
    for (u32 di : dir_order) {
      bool child_action_ok = false;
      bool child_path_ok = false;
      for (u32 p = dir_child_offsets[di]; p < dir_child_offsets[di + 1]; ++p) {
        const u32 child = dir_child_indices[p];
        if (dir_action_ok[child]) {
          child_action_ok = true;
          if (dir_path_ok[child]) child_path_ok = true;
        }
      }
      for (u32 p = dir_file_offsets[di]; p < dir_file_offsets[di + 1]; ++p) {
        const u32 ci = dir_file_indices[p];
        if (change_action_ok[ci]) {
          child_action_ok = true;
          if (change_path_ok[ci]) child_path_ok = true;
        }
      }
      const u32 own = di < dir_own_change.size() ? dir_own_change[di] : NO_INDEX;
      bool own_action_ok = false;
      if (own != NO_INDEX && own < nchanges) {
        const u32 code = own < change_action.size() ? change_action[own] : 0;
        own_action_ok = actions_mask == 0 ||
                        (code < 32 && ((actions_mask >> code) & 1u) != 0);
        if (change_path_ok[own]) child_path_ok = true;
        if (change_action_ok[own]) child_action_ok = true;
      }
      dir_path_ok[di] = 1;  // (not pattern_active) holds when no pattern
      dir_action_ok[di] = (own_action_ok || child_action_ok) ? 1 : 0;
      dir_faded[di] =
          (filter_directories && own != NO_INDEX && !own_action_ok) ? 1 : 0;
      dir_visible[di] = (dir_path_ok[di] && dir_action_ok[di]) ? 1 : 0;
    }
    if (!dir_visible.empty()) {
      dir_path_ok[0] = 1;
      dir_action_ok[0] = 1;
      dir_faded[0] = 0;
      dir_visible[0] = nchanges != 0 ? 1 : 0;
    }
    return build_rows_from_flags(has_exclusion, row_excluded, row_explicit,
                                 show_excluded, folded_parent, generation);
  }

  u32 build_rows_from_flags(bool has_exclusion,
                            const std::vector<u8>& row_excluded,
                            const std::vector<u8>& row_explicit,
                            bool show_excluded,
                            const std::vector<u8>& folded_parent,
                            u32 generation) {
    std::vector<u8> row_visible(paths.size(), 0);
    std::vector<u8> row_path_ok(paths.size(), 0);
    std::vector<u8> row_faded(paths.size(), 0);
    for (std::size_t i = 0; i < paths.size(); ++i) {
      const u32 ci = i < change_index.size() ? change_index[i] : NO_INDEX;
      if (is_dir[i]) {
        const u32 di = i < own_dir_index.size() ? own_dir_index[i] : 0;
        row_visible[i] = di < dir_visible.size() ? dir_visible[di] : 0;
        row_path_ok[i] = di < dir_path_ok.size() ? dir_path_ok[di] : 0;
        row_faded[i] = di < dir_faded.size() ? dir_faded[di] : 0;
      } else if (ci != NO_INDEX) {
        row_visible[i] = ci < change_visible.size() ? change_visible[ci] : 0;
        row_path_ok[i] = ci < change_path_ok.size() ? change_path_ok[ci] : 0;
      }
    }
    return emit(row_visible, row_path_ok, row_faded, row_excluded, row_explicit,
                has_exclusion, show_excluded, folded_parent, generation);
  }

  // Full-path-pattern variant of filter(). The no-pattern fast path above is
  // kept unchanged; pattern searches are interactive and much rarer.
  u32 filter_pattern(const std::string& pattern, bool pattern_is_glob,
                     bool directories_only, bool include_contents,
                     bool has_exclusion, const std::vector<u8>& row_excluded,
                     const std::vector<u8>& row_explicit, bool show_excluded,
                     const std::vector<u8>& folded_parent, u32 generation) {
    const std::size_t ndirs = dir_parent.size();
    const std::size_t nchanges = change_dir.size();
    std::vector<u8> dir_matched(ndirs, 0);
    for (std::size_t di = 0; di < ndirs; ++di) {
      const u32 row = di < dir_row.size() ? dir_row[di] : NO_INDEX;
      bool matched = false;
      if (row != NO_INDEX) {
        matched = folded_matches(
            row < folded_names.size() ? folded_names[row] : std::string(),
            row < folded_paths.size() ? folded_paths[row] : std::string(), true,
            pattern, pattern_is_glob, directories_only);
      }
      const u32 parent = di < dir_parent.size() ? dir_parent[di] : NO_INDEX;
      if (!matched && parent != NO_INDEX && parent < ndirs) {
        matched = dir_matched[parent] != 0;
      }
      dir_matched[di] = matched ? 1 : 0;
    }
    // FlatChangeModel only recomputes flags for changes in directory.files,
    // i.e. files. Directory-own changes keep the flags from the previous
    // (pattern-less) pass, so seed with filter() before calling this kernel.
    for (u32 p = 0; p < dir_file_offsets[ndirs]; ++p) {
      const u32 ci = dir_file_indices[p];
      const u32 row = ci < row_of_change.size() ? row_of_change[ci] : NO_INDEX;
      bool path_ok = false;
      if (row != NO_INDEX) {
        path_ok = folded_matches(
            row < folded_names.size() ? folded_names[row] : std::string(),
            row < folded_paths.size() ? folded_paths[row] : std::string(), false,
            pattern, pattern_is_glob, directories_only);
      }
      const u32 di = ci < change_dir.size() ? change_dir[ci] : NO_INDEX;
      if (!path_ok && include_contents && di != NO_INDEX && di < ndirs &&
          dir_matched[di]) {
        path_ok = true;
      }
      const u32 code = ci < change_action.size() ? change_action[ci] : 0;
      const bool keep = actions_mask_active_
                            ? (code < 32 && ((actions_mask_ >> code) & 1u) != 0)
                            : true;
      change_path_ok[ci] = path_ok ? 1 : 0;
      change_action_ok[ci] = keep ? 1 : 0;
      change_visible[ci] = (path_ok && keep) ? 1 : 0;
    }
    for (u32 di : dir_order) {
      bool child_action_ok = false;
      bool child_path_ok = false;
      for (u32 p = dir_child_offsets[di]; p < dir_child_offsets[di + 1]; ++p) {
        const u32 child = dir_child_indices[p];
        if (dir_action_ok[child]) {
          child_action_ok = true;
          if (dir_path_ok[child]) child_path_ok = true;
        }
      }
      for (u32 p = dir_file_offsets[di]; p < dir_file_offsets[di + 1]; ++p) {
        const u32 ci = dir_file_indices[p];
        if (change_action_ok[ci]) {
          child_action_ok = true;
          if (change_path_ok[ci]) child_path_ok = true;
        }
      }
      const u32 own = di < dir_own_change.size() ? dir_own_change[di] : NO_INDEX;
      bool own_action_ok = false;
      if (own != NO_INDEX && own < nchanges) {
        const u32 code = own < change_action.size() ? change_action[own] : 0;
        own_action_ok = actions_mask_active_
                            ? (code < 32 && ((actions_mask_ >> code) & 1u) != 0)
                            : true;
        if (change_path_ok[own]) child_path_ok = true;
        if (change_action_ok[own]) child_action_ok = true;
      }
      const u32 row = di < dir_row.size() ? dir_row[di] : NO_INDEX;
      bool direct = false;
      if (row != NO_INDEX) {
        direct = folded_matches(
            row < folded_names.size() ? folded_names[row] : std::string(),
            row < folded_paths.size() ? folded_paths[row] : std::string(), true,
            pattern, pattern_is_glob, directories_only);
      }
      const u32 parent = di < dir_parent.size() ? dir_parent[di] : NO_INDEX;
      if (!direct && include_contents && parent != NO_INDEX && parent < ndirs &&
          dir_matched[parent]) {
        direct = true;
      }
      dir_path_ok[di] = (direct || child_path_ok) ? 1 : 0;
      dir_action_ok[di] = (own_action_ok || child_action_ok) ? 1 : 0;
      dir_faded[di] =
          (filter_directories_ && own != NO_INDEX && !own_action_ok) ? 1 : 0;
      dir_visible[di] = (dir_path_ok[di] && dir_action_ok[di]) ? 1 : 0;
    }
    if (!dir_visible.empty()) {
      dir_path_ok[0] = 1;
      dir_action_ok[0] = 1;
      dir_faded[0] = 0;
      dir_visible[0] = nchanges != 0 ? 1 : 0;
    }
    return build_rows_from_flags(has_exclusion, row_excluded, row_explicit,
                                 show_excluded, folded_parent, generation);
  }

};

// Experimental rsync itemized-record parser. Mirrors backend/rsync_parser.py
// field for field so the lazy Change sequence can be validated byte-for-byte.
struct ParsedRecords {
  std::vector<std::string> paths;
  std::vector<int> actions;
  std::vector<int> kinds;
  std::vector<i64> sizes;
  std::vector<std::string> codes;
  std::vector<std::string> times;      // empty means None
  std::vector<std::string> link_targets;
  std::vector<std::string> reasons;
  std::vector<u8> size_none;           // deletion records carry no size
  std::vector<std::string> skipped;    // informational and root records
  std::string error;                   // first parse error, empty when valid
};

// Mirrors backend/rsync_parser.describe_itemized.
static std::string describe_itemized(const std::string& code, bool deleting) {
  if (deleting) return "destination-only object will be deleted";
  if (code.size() < 11) return "unrecognized rsync action";
  const std::string attrs = code.substr(2, 9);
  if (attrs.find('+') != std::string::npos) return "new object";
  static const char* labels[8] = {
      "checksum/value", "size", "modification time", "permissions",
      "owner", "group", "ACL", "extended attributes"};
  std::string reason;
  for (int position = 0; position < 8; ++position) {
    if (position < static_cast<int>(attrs.size()) &&
        attrs[position] != '.' && attrs[position] != ' ') {
      if (!reason.empty()) reason += ", ";
      reason += labels[position];
    }
  }
  return reason.empty() ? "rsync reported a change" : reason;
}

static ParsedRecords parse_records_native(const std::string& input,
                                          bool delete_enabled) {
  static const std::string sep = "|qpy-rsync|";
  static const std::string link_marker = " -> ";
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
    if (a == std::string::npos) {
      out.skipped.push_back(line);  // informational line, not an error
      continue;
    }
    std::size_t b = line.find(sep, a + sep.size());
    if (b == std::string::npos) {
      out.error = "Expected four output fields, got 2";
      return out;
    }
    std::size_t c = line.find(sep, b + sep.size());
    if (c == std::string::npos) {
      out.error = "Expected four output fields, got 3";
      return out;
    }
    if (line.find(sep, c + sep.size()) != std::string::npos) {
      out.error = "Field separator appears in filename; record is ambiguous";
      return out;
    }
    const std::string code = line.substr(0, a);
    const std::string size_text = line.substr(a + sep.size(), b - a - sep.size());
    const std::string time_text = line.substr(b + sep.size(), c - b - sep.size());
    std::string name_and_link = line.substr(c + sep.size());
    const bool deleting = code.rfind("*deleting", 0) == 0;
    if (!deleting && code.size() != 11) {
      out.error = "Invalid itemized code: '" + code + "'";
      return out;
    }
    if (name_and_link.find('\0') != std::string::npos) {
      out.error = "NUL in rsync output is unsupported";
      return out;
    }
    i64 size = 0;
    bool size_none = false;
    if (deleting) {
      size_none = true;
    } else {
      bool digits = !size_text.empty();
      for (char ch : size_text) {
        if (ch < '0' || ch > '9') {
          digits = false;
          break;
        }
      }
      if (!digits) {
        out.error = "Invalid size field: '" + size_text + "'";
        return out;
      }
      try {
        size = std::stoll(size_text);
      } catch (...) {
        out.error = "Invalid size field: '" + size_text + "'";
        return out;
      }
    }
    std::string link_target;
    if (!deleting && code.size() > 1 && code[1] == 'L') {
      std::size_t marker = name_and_link.find(link_marker);
      if (marker != std::string::npos) {
        link_target = name_and_link.substr(marker + link_marker.size());
        name_and_link = name_and_link.substr(0, marker);
      }
    }
    if (name_and_link == "." || name_and_link == "./") {
      out.skipped.push_back(line);
      if (end == input.size()) break;
      continue;
    }
    if (name_and_link.empty()) {
      out.error = "Empty change path";
      return out;
    }
    int action = 0;  // create
    if (deleting) {
      action = delete_enabled ? 3 : 4;  // delete / destination_only
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
        action = metadata ? 2 : 5;  // metadata / no change
      }
    }
    int kind = 0;  // file
    if (deleting) {
      kind = (!name_and_link.empty() && name_and_link.back() == '/') ? 1 : 0;
    } else if (code.size() > 1) {
      switch (code[1]) {
        case 'f': kind = 0; break;
        case 'd': kind = 1; break;
        case 'L': kind = 2; break;
        case 'D': kind = 3; break;
        case 'S': kind = 4; break;
        default: kind = 5;  // unknown
      }
    }
    out.paths.push_back(std::move(name_and_link));
    out.actions.push_back(action);
    out.kinds.push_back(kind);
    out.sizes.push_back(size);
    out.codes.push_back(code);
    out.times.push_back(deleting ? std::string() : time_text);
    out.link_targets.push_back(std::move(link_target));
    out.reasons.push_back(describe_itemized(code, deleting));
    out.size_none.push_back(size_none ? 1 : 0);
    if (end == input.size()) break;
  }
  return out;
}

// Stage 5: the build_execution_plan loop. Python supplies the per-change
// effective "included" decision (decision inheritance stays in Python); this
// kernel emits compact item arrays, summary counters and the exact byte
// stream used for the items fingerprint.
struct PlanArrays {
  std::vector<std::string> paths;
  std::vector<int> actions;              // effective action code
  std::vector<int> comparison_actions;
  std::vector<int> kinds;
  std::vector<u8> included;
  std::vector<u8> destructive;
  std::vector<i64> sizes;
  std::vector<u8> size_none;
  std::vector<std::string> delete_paths;
  std::vector<int> delete_kinds;
  std::string digest;                    // feed directly to sha256 in Python
  u64 included_count = 0;
  u64 excluded = 0;
  u64 retained_destination_only = 0;
  u64 destructive_count = 0;
  u64 creates = 0;
  u64 updates = 0;
  u64 metadata = 0;
  u64 deletions = 0;
  i64 total_size = 0;
  i64 included_size = 0;
};

static const char* action_value(int code) {
  static const char* values[7] = {
      "create", "update_content", "update_metadata", "delete",
      "destination_only", "no_change", "message"};
  return code >= 0 && code < 7 ? values[code] : "message";
}

static const char* kind_value(int code) {
  static const char* values[6] = {
      "file", "directory", "symlink", "device", "special", "unknown"};
  return code >= 0 && code < 6 ? values[code] : "unknown";
}

static PlanArrays build_plan_arrays(const std::vector<std::string>& paths,
                                    const std::vector<int>& actions,
                                    const std::vector<int>& kinds,
                                    const std::vector<i64>& sizes,
                                    const std::vector<u8>& size_none,
                                    const std::vector<u8>& included) {
  PlanArrays out;
  const std::size_t count = paths.size();
  out.paths.reserve(count);
  out.actions.reserve(count);
  out.comparison_actions.reserve(count);
  out.kinds.reserve(count);
  out.included.reserve(count);
  out.destructive.reserve(count);
  out.sizes.reserve(count);
  for (std::size_t i = 0; i < count; ++i) {
    const int comparison = i < actions.size() ? actions[i] : 0;
    if (comparison == 5 || comparison == 6) continue;  // no change / message
    const bool selected = i < included.size() && included[i] != 0;
    const int effective =
        (comparison == 4 && selected) ? 3 : comparison;  // dest-only -> delete
    const bool destructive = selected && effective == 3;
    const i64 size = i < sizes.size() ? sizes[i] : 0;
    const int kind = i < kinds.size() ? kinds[i] : 0;

    std::string clean = paths[i];
    while (!clean.empty() && clean.back() == '/') clean.pop_back();
    out.paths.push_back(clean);
    out.actions.push_back(effective);
    out.comparison_actions.push_back(comparison);
    out.kinds.push_back(kind);
    out.included.push_back(selected ? 1 : 0);
    out.destructive.push_back(destructive ? 1 : 0);
    out.sizes.push_back(size);
    out.size_none.push_back(
        i < size_none.size() && size_none[i] != 0 ? 1 : 0);

    if (selected) {
      ++out.included_count;
      if (destructive) ++out.destructive_count;
      out.included_size += size;
      if (effective == 0 || effective == 1) out.total_size += size;
      if (effective == 0) ++out.creates;
      else if (effective == 1) ++out.updates;
      else if (effective == 2) ++out.metadata;
      else if (effective == 3) {
        ++out.deletions;
        out.delete_paths.push_back(clean);
        out.delete_kinds.push_back(kind);
      }
    } else if (comparison == 4) {
      ++out.retained_destination_only;
    } else {
      ++out.excluded;
    }

    out.digest += clean;
    out.digest += action_value(effective);
    out.digest += kind_value(kind);
    out.digest += selected ? '1' : '0';
  }
  return out;
}


NB_MODULE(_qpy_native, m) {
  nb::class_<PlanArrays>(m, "PlanArrays")
      .def_ro("paths", &PlanArrays::paths)
      .def_ro("actions", &PlanArrays::actions)
      .def_ro("comparison_actions", &PlanArrays::comparison_actions)
      .def_ro("kinds", &PlanArrays::kinds)
      .def_ro("included", &PlanArrays::included)
      .def_ro("destructive", &PlanArrays::destructive)
      .def_ro("sizes", &PlanArrays::sizes)
      .def_ro("size_none", &PlanArrays::size_none)
      .def_ro("delete_paths", &PlanArrays::delete_paths)
      .def_ro("delete_kinds", &PlanArrays::delete_kinds)
      .def_ro("digest", &PlanArrays::digest)
      .def_ro("included_count", &PlanArrays::included_count)
      .def_ro("excluded", &PlanArrays::excluded)
      .def_ro("retained_destination_only", &PlanArrays::retained_destination_only)
      .def_ro("destructive_count", &PlanArrays::destructive_count)
      .def_ro("creates", &PlanArrays::creates)
      .def_ro("updates", &PlanArrays::updates)
      .def_ro("metadata", &PlanArrays::metadata)
      .def_ro("deletions", &PlanArrays::deletions)
      .def_ro("total_size", &PlanArrays::total_size)
      .def_ro("included_size", &PlanArrays::included_size);
  m.def("build_plan_arrays", &build_plan_arrays, nb::arg("paths"),
        nb::arg("actions"), nb::arg("kinds"), nb::arg("sizes"),
        nb::arg("size_none"), nb::arg("included"));
  nb::class_<NativeFilter>(m, "NativeFilter")
      .def(nb::init<std::vector<int>, std::vector<int>, std::vector<bool>,
                    std::vector<i64>, std::size_t>())
      .def("apply", &NativeFilter::apply);
  nb::class_<NativeComparison>(m, "NativeComparison")
      .def(nb::init<std::vector<std::string>, std::vector<std::string>,
                    std::vector<std::string>, std::vector<int>,
                    std::vector<int>, std::vector<int>, std::vector<bool>,
                    std::vector<i64>, std::vector<i64>>())
      .def("row_count", &NativeComparison::row_count)
      .def("dir_count", &NativeComparison::dir_count)
      .def("apply", &NativeComparison::apply, nb::arg("row_visible"),
           nb::arg("row_path_ok"), nb::arg("row_faded"),
           nb::arg("row_excluded"), nb::arg("row_explicit"),
           nb::arg("folded_parent"), nb::arg("has_exclusion"),
           nb::arg("show_excluded"), nb::arg("generation"))
      .def("set_structure", &NativeComparison::set_structure,
           nb::arg("change_dir"), nb::arg("change_is_dir"),
           nb::arg("change_action"), nb::arg("dir_parent"),
           nb::arg("dir_own_change"))
      .def("set_actions", &NativeComparison::set_actions, nb::arg("actions"))
      .def("set_action_filter", &NativeComparison::set_action_filter,
           nb::arg("mask"))
      .def("set_filter_directories",
           &NativeComparison::set_filter_directories, nb::arg("enabled"))
      .def("filter_pattern", &NativeComparison::filter_pattern,
           nb::arg("pattern"), nb::arg("pattern_is_glob"),
           nb::arg("directories_only"), nb::arg("include_contents"),
           nb::arg("has_exclusion"), nb::arg("row_excluded"),
           nb::arg("row_explicit"), nb::arg("show_excluded"),
           nb::arg("folded_parent"), nb::arg("generation"))
      .def("search_rows", &NativeComparison::search_rows, nb::arg("pattern"),
           nb::arg("is_glob"), nb::arg("directories_only"),
           nb::arg("show_excluded"), nb::arg("row_excluded"))
      .def("filter", &NativeComparison::filter, nb::arg("actions_mask"),
           nb::arg("filter_directories"), nb::arg("has_exclusion"),
           nb::arg("row_excluded"), nb::arg("row_explicit"),
           nb::arg("show_excluded"), nb::arg("folded_parent"),
           nb::arg("generation"))
      .def_ro("visible_rows", &NativeComparison::visible_rows)
      .def_ro("visible_changes", &NativeComparison::visible_changes)
      .def_ro("dir_action_ok", &NativeComparison::dir_action_ok)
      .def_ro("dir_visible", &NativeComparison::dir_visible)
      .def_ro("dir_path_ok", &NativeComparison::dir_path_ok)
      .def_ro("dir_faded", &NativeComparison::dir_faded)
      .def_ro("change_visible", &NativeComparison::change_visible)
      .def_ro("change_action_ok", &NativeComparison::change_action_ok)
      .def_ro("change_path_ok", &NativeComparison::change_path_ok)
      .def_ro("dir_file_offsets", &NativeComparison::dir_file_offsets)
      .def_ro("dir_file_indices", &NativeComparison::dir_file_indices)
      .def_ro("dir_own_change", &NativeComparison::dir_own_change)
      .def_ro("dir_counts", &NativeComparison::dir_counts)
      .def_ro("dir_sizes", &NativeComparison::dir_sizes)
      .def_ro("dir_totals", &NativeComparison::dir_totals);
  nb::class_<ParsedRecords>(m, "ParsedRecords")
      .def_ro("paths", &ParsedRecords::paths)
      .def_ro("actions", &ParsedRecords::actions)
      .def_ro("kinds", &ParsedRecords::kinds)
      .def_ro("sizes", &ParsedRecords::sizes)
      .def_ro("codes", &ParsedRecords::codes)
      .def_ro("times", &ParsedRecords::times)
      .def_ro("link_targets", &ParsedRecords::link_targets)
      .def_ro("reasons", &ParsedRecords::reasons)
      .def_ro("size_none", &ParsedRecords::size_none)
      .def_ro("skipped", &ParsedRecords::skipped)
      .def_ro("error", &ParsedRecords::error);
  m.def("parse_records", &parse_records_native, nb::arg("input"),
        nb::arg("delete_enabled"));
}
