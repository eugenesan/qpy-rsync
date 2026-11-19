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

NB_MODULE(_qpy_native, m) {
  nb::class_<NativeFilter>(m, "NativeFilter")
      .def(nb::init<std::vector<int>, std::vector<int>, std::vector<bool>,
                    std::vector<i64>, std::size_t>())
      .def("apply", &NativeFilter::apply);
}
