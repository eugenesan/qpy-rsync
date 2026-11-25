// Shared data store and Qt models for the native Qt model experiment.
#ifndef QPY_NATIVE_QT_MODEL_HPP
#define QPY_NATIVE_QT_MODEL_HPP

#include <QAbstractItemModel>
#include <QAbstractTableModel>
#include <QElapsedTimer>
#include <QVariant>
#include <QAbstractItemModel>

#include <algorithm>
#include <map>
#include <set>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <numeric>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

using DecisionHook = void (*)(int path_id, int decision);
inline DecisionHook g_decision_hook = nullptr;

enum Action { Create = 0, Update = 1, Metadata = 2, Delete = 3, DestOnly = 4, NoChange = 5 };
enum Decision { Inherit = 0, Include = 1, Exclude = 2, DeleteRequest = 3 };

inline QString qpy_format_size(long long bytes) {
  static const char* units[] = {"B", "KiB", "MiB", "GiB", "TiB"};
  double value = static_cast<double>(bytes);
  for (int i = 0; i < 5; ++i) {
    if (value < 1024.0 || i == 4) {
      if (i == 0) return QString::number(static_cast<long long>(value)) + " B";
      return QString::number(value, 'f', 1) + " " + QString(units[i]);
    }
    value /= 1024.0;
  }
  return {};
}

struct DataStore {
  std::vector<std::string> paths;
  std::vector<int> actions;
  std::vector<int> kinds;
  std::vector<long long> sizes;
  std::vector<std::string> times;
  std::vector<int> decisions;
  // Volatile view state owned by native.
  std::vector<int> parents;
  std::vector<int> is_dir;
  // Synthesized parent folders are navigation rows, not comparison items.
  std::vector<char> synthetic;
  std::vector<int> depth;
  std::vector<std::string> names;
  std::vector<std::string> folded_names;
  std::vector<std::string> folded_paths;
  std::vector<char> collapsed;
  std::unordered_map<std::string, int> path_to_id;
  int action_mask = 0;  // 0 means "all actions"
  std::string pattern;
  bool pattern_glob = false;
  bool dirs_only = false;
  bool include_contents = false;
  int sort_column = 0;
  bool sort_desc = false;
  // Stable decision key: row positions are volatile after sort/filter.
  std::vector<std::pair<int, int>> decision_log;
  std::vector<int> visible;
  std::vector<int> row_of_id;
  bool show_excluded = false;
  bool filter_directories = false;
  std::vector<char> faded;
  // Folder aggregates and per-visible-row striping owned by native.
  std::vector<long long> dir_items;
  std::vector<long long> dir_size;
  std::vector<char> stripe;
  std::string root_source = "Source";
  std::string root_dest = "Destination";
  std::vector<QString> action_colours;
  // Destination-side content, filled in by the async destination listing.
  std::unordered_map<std::string, std::pair<long long, std::string>> dest_metadata;
  std::vector<long long> dest_sizes;
  std::vector<std::string> dest_times;
  std::vector<long long> dest_items;
  std::vector<char> dir_has_children;
  std::unordered_map<std::string, QIcon> file_icons;
  QIcon folder_icon;
  QIcon root_icon;
  static const char* root_path() {
    static const char* value = "\x01__qpy_root__";
    return value;
  }

  void generate(int count) {
    paths.clear();
    actions.clear();
    kinds.clear();
    sizes.clear();
    decisions.clear();
    decision_log.clear();
    paths.reserve(count);
    actions.reserve(count);
    kinds.reserve(count);
    sizes.reserve(count);
    decisions.reserve(count);
    for (int i = 0; i < count; ++i) {
      std::string path = "d" + std::to_string(i % 30000) +
                         "/f" + std::to_string(i) + ".txt";
      paths.push_back(std::move(path));
      actions.push_back(i % 17 == 0 ? Delete : (i % 5 == 0 ? Update : Create));
      kinds.push_back(i % 97 == 0 ? 1 : 0);  // 1 = directory
      sizes.push_back((i * 37) % 100000);
      decisions.push_back(Inherit);
    }
    synthetic.assign(count, 0);
    visible.resize(count);
    std::iota(visible.begin(), visible.end(), 0);
  }

  bool load_binary(const std::string& file, qint64* read_ms, qint64* parse_ms) {
    QElapsedTimer timer;
    timer.start();
    std::ifstream input(file, std::ios::binary | std::ios::ate);
    if (!input) return false;
    std::streamsize size = input.tellg();
    input.seekg(0);
    std::vector<char> raw(static_cast<std::size_t>(size));
    input.read(raw.data(), size);
    *read_ms = timer.elapsed();
    timer.restart();
    if (size < 16 || std::memcmp(raw.data(), "QPYN", 4) != 0) return false;
    unsigned version = 0;
    std::memcpy(&version, raw.data() + 4, 4);
    unsigned long long count64 = 0;
    std::memcpy(&count64, raw.data() + 8, 8);
    if (version != 1 || count64 > 100000000ULL) return false;
    const int count = static_cast<int>(count64);
    std::size_t at = 16;
    std::vector<unsigned> offsets(count + 1);
    std::memcpy(offsets.data(), raw.data() + at, (count + 1) * 4);
    at += (count + 1) * 4;
    const char* blob = raw.data() + at;
    at += offsets[count];
    paths.clear();
    paths.reserve(count);
    for (int i = 0; i < count; ++i) {
      paths.emplace_back(blob + offsets[i], offsets[i + 1] - offsets[i]);
    }
    actions.resize(count);
    kinds.resize(count);
    sizes.resize(count);
    decisions.resize(count);
    std::memcpy(actions.data(), raw.data() + at, count);
    at += count;
    std::memcpy(kinds.data(), raw.data() + at, count);
    at += count;
    std::memcpy(sizes.data(), raw.data() + at, count * 4);
    at += count * 4;
    std::memcpy(decisions.data(), raw.data() + at, count);
    decision_log.clear();
    synthetic.assign(count, 0);
    visible.resize(count);
    std::iota(visible.begin(), visible.end(), 0);
    *parse_ms = timer.elapsed();
    return true;
  }

  void derive_structure(int start, int end) {
    for (int i = start; i < end; ++i) {
      const std::string& path = paths[i];
      std::size_t slash = path.rfind('/');
      parents[i] = -1;
      if (slash != std::string::npos) {
        auto parent_it = path_to_id.find(path.substr(0, slash));
        if (parent_it != path_to_id.end()) parents[i] = parent_it->second;
      }
      is_dir[i] = (i < static_cast<int>(kinds.size()) && kinds[i] == 1) ? 1 : 0;
      depth[i] = parents[i] >= 0 ? depth[parents[i]] + 1 : 0;
    }
  }

  void derive_text(int start, int end) {
    for (int i = start; i < end; ++i) {
      const std::string& path = paths[i];
      std::size_t slash = path.rfind('/');
      std::string name = slash == std::string::npos
                             ? path
                             : path.substr(slash + 1);
      names[i] = name;
      folded_names[i].resize(name.size());
      for (std::size_t j = 0; j < name.size(); ++j) {
        folded_names[i][j] = static_cast<char>(
            std::tolower(static_cast<unsigned char>(name[j])));
      }
      folded_paths[i].resize(path.size());
      for (std::size_t j = 0; j < path.size(); ++j) {
        folded_paths[i][j] = static_cast<char>(
            std::tolower(static_cast<unsigned char>(path[j])));
      }
    }
  }

  void derive_range(int start, int end) {
    derive_structure(start, end);
    derive_text(start, end);
  }

  void load_direct(const std::vector<std::string>& paths_,
                   const std::vector<int>& actions_,
                   const std::vector<int>& kinds_,
                   const std::vector<long long>& sizes_,
                   const std::vector<int>& decisions_,
                   const std::vector<std::string>& times_) {
    paths = paths_;
    actions = actions_;
    kinds = kinds_;
    sizes = sizes_;
    times = times_;
    decisions = decisions_;
    const int count = static_cast<int>(paths.size());
    parents.resize(count);
    is_dir.resize(count);
    synthetic.assign(count, 0);
    depth.resize(count);
    names.resize(count);
    folded_names.resize(count);
    folded_paths.resize(count);
    path_to_id.clear();
    for (int i = 0; i < count; ++i) path_to_id[paths[i]] = i;
    derive_range(0, count);
    decision_log.clear();
    collapsed.assign(paths.size(), 0);
    action_mask = 0;
    pattern.clear();
    sort_column = 0;
    sort_desc = false;
    visible.resize(paths.size());
    std::iota(visible.begin(), visible.end(), 0);
  }

  // Append extra records (typically unchanged items) without re-deriving the
  // rows that were already loaded.
  void append_direct(const std::vector<std::string>& paths_,
                     const std::vector<int>& actions_,
                     const std::vector<int>& kinds_,
                     const std::vector<long long>& sizes_,
                     const std::vector<int>& decisions_,
                     const std::vector<std::string>& times_) {
    const int start = static_cast<int>(paths.size());
    const int added = static_cast<int>(paths_.size());
    paths.insert(paths.end(), paths_.begin(), paths_.end());
    actions.insert(actions.end(), actions_.begin(), actions_.end());
    kinds.insert(kinds.end(), kinds_.begin(), kinds_.end());
    sizes.insert(sizes.end(), sizes_.begin(), sizes_.end());
    times.insert(times.end(), times_.begin(), times_.end());
    decisions.insert(decisions.end(), decisions_.begin(), decisions_.end());
    const int count = static_cast<int>(paths.size());
    parents.resize(count);
    is_dir.resize(count);
    synthetic.resize(count, 0);
    depth.resize(count);
    names.resize(count);
    folded_names.resize(count);
    folded_paths.resize(count);
    for (int i = start; i < count; ++i) path_to_id[paths[i]] = i;
    derive_range(start, count);
    collapsed.resize(count, 0);
    visible.resize(count);
    std::iota(visible.begin(), visible.end(), 0);
  }

  // Drop trailing records when unchanged items are removed.
  void truncate(int count) {
    if (count < 0 || count >= static_cast<int>(paths.size())) return;
    paths.resize(count);
    actions.resize(count);
    kinds.resize(count);
    sizes.resize(count);
    times.resize(count);
    decisions.resize(count);
    parents.resize(count);
    is_dir.resize(count);
    synthetic.resize(count);
    depth.resize(count);
    names.resize(count);
    folded_names.resize(count);
    folded_paths.resize(count);
    collapsed.resize(count);
    // Erase only the removed tail; the prefix keeps its id mapping.
    for (auto it = path_to_id.begin(); it != path_to_id.end();) {
      if (it->second >= count) it = path_to_id.erase(it);
      else ++it;
    }
    decision_log.clear();
    visible.resize(count);
    std::iota(visible.begin(), visible.end(), 0);
  }

  // Synthesize one row per parent directory plus a virtual root row, then
  // lay the rows out in tree order (folder, its files, then its subfolders).
  void add_directories() {
    synthetic.resize(paths.size(), 0);
    std::set<std::string> dirs;
    for (const std::string& path : paths) {
      if (path == root_path()) continue;
      std::size_t slash = path.rfind('/');
      std::string parent = slash == std::string::npos ? "" : path.substr(0, slash);
      while (!parent.empty()) {
        dirs.insert(parent);
        std::size_t next = parent.rfind('/');
        parent = next == std::string::npos ? "" : parent.substr(0, next);
      }
    }
    const int start = static_cast<int>(paths.size());
    for (const std::string& dir : dirs) {
      if (path_to_id.count(dir)) continue;
      int id = static_cast<int>(paths.size());
      paths.push_back(dir);
      actions.push_back(NoChange);
      kinds.push_back(1);
      sizes.push_back(0);
      times.push_back("");
      decisions.push_back(Inherit);
      synthetic.push_back(1);
      path_to_id[dir] = id;
    }
    int root = -1;
    auto root_it = path_to_id.find(root_path());
    if (root_it == path_to_id.end()) {
      root = static_cast<int>(paths.size());
      paths.push_back(root_path());
      actions.push_back(NoChange);
      kinds.push_back(1);
      sizes.push_back(0);
      times.push_back("");
      decisions.push_back(Inherit);
      synthetic.push_back(1);
      path_to_id[root_path()] = root;
    } else {
      root = root_it->second;
    }
    const int count = static_cast<int>(paths.size());
    parents.resize(count);
    is_dir.resize(count);
    depth.resize(count);
    names.resize(count);
    folded_names.resize(count);
    folded_paths.resize(count);
    collapsed.resize(count, 0);
    // Re-derive the structure now that the synthesized folders are in the
    // map; the display text of the existing rows is already cached.
    derive_structure(0, count);
    derive_text(start, count);
    // Top-level rows hang off the virtual root.
    for (int i = 0; i < count; ++i) {
      if (i == root) continue;
      if (parents[i] < 0) parents[i] = root;
    }
    parents[root] = -1;
    is_dir[root] = 1;
    for (int i = 0; i < count; ++i) {
      int d = 0;
      int parent = parents[i];
      while (parent >= 0 && d < 64) {
        ++d;
        parent = parent < static_cast<int>(parents.size()) ? parents[parent] : -1;
      }
      depth[i] = d;
    }
    depth[root] = 0;
    names[root] = root_source;
    folded_names[root] = root_source;
    folded_paths[root] = root_source;
    dir_has_children.assign(count, 0);
    for (int i = 0; i < count; ++i) {
      const int parent = i < static_cast<int>(parents.size()) ? parents[i] : -1;
      if (parent >= 0 && parent < count && parent != root) {
        dir_has_children[parent] = 1;
      }
    }
    visible = tree_order();
    row_of_id.assign(count, -1);
    for (int row = 0; row < static_cast<int>(visible.size()); ++row) {
      row_of_id[visible[row]] = row;
    }
    faded.assign(count, 0);
    compute_aggregates();
    compute_stripes();
  }

  bool counts_as_item(int i) const {
    if (i < 0 || i >= static_cast<int>(paths.size())) return false;
    const bool directory =
        i < static_cast<int>(is_dir.size()) && is_dir[i] != 0;
    if (directory) {
      if (i < static_cast<int>(synthetic.size()) && synthetic[i]) {
        return false;
      }
      if (i >= static_cast<int>(row_of_id.size()) || row_of_id[i] < 0) {
        return false;
      }
      if (i < static_cast<int>(faded.size()) && faded[i]) return false;
    }
    if (i < static_cast<int>(decisions.size()) &&
        decisions[i] == Exclude) {
      return false;
    }
    if (directory) return true;
    return matches(i);
  }

  void compute_destination_counts() {
    dest_items.assign(paths.size(), 0);
    for (int i = 0; i < static_cast<int>(paths.size()); ++i) {
      if (!counts_as_item(i)) continue;
      const int action = i < static_cast<int>(actions.size()) ? actions[i] : NoChange;
      if (action == Create) continue;
      int parent = i < static_cast<int>(parents.size()) ? parents[i] : -1;
      while (parent >= 0) {
        dest_items[parent] += 1;
        parent = parent < static_cast<int>(parents.size()) ? parents[parent] : -1;
      }
    }
  }

  void apply_destination_metadata(
      const std::unordered_map<std::string, std::pair<long long, std::string>>& metadata,
      bool merge) {
    if (!merge) dest_metadata.clear();
    for (const auto& entry : metadata) dest_metadata[entry.first] = entry.second;
    dest_sizes.assign(paths.size(), 0);
    dest_times.assign(paths.size(), "");
    dest_items.assign(paths.size(), 0);
    for (int i = 0; i < static_cast<int>(paths.size()); ++i) {
      auto it = dest_metadata.find(paths[i]);
      if (it != dest_metadata.end()) {
        dest_sizes[i] = it->second.first;
        dest_times[i] = it->second.second;
      }
    }
    // Roll the per-file values up through the parent chain. The old
    // per-directory scan of every path was O(dirs * paths) and froze the UI
    // on trees with tens of thousands of folders.
    for (int i = 0; i < static_cast<int>(paths.size()); ++i) {
      if (i < static_cast<int>(is_dir.size()) && is_dir[i]) continue;
      const int action = i < static_cast<int>(actions.size()) ? actions[i] : NoChange;
      if (action == Create) continue;
      if (i < static_cast<int>(decisions.size()) && decisions[i] == Exclude) continue;
      int parent = i < static_cast<int>(parents.size()) ? parents[i] : -1;
      while (parent >= 0) {
        dest_sizes[parent] += dest_sizes[i];
        dest_items[parent] += 1;
        parent = parent < static_cast<int>(parents.size()) ? parents[parent] : -1;
      }
    }
    compute_destination_counts();
  }

  void compute_aggregates() {
    // A reported directory is an item of its parent folder; synthesized
    // navigation folders are never counted. Subtrees keep their counts when
    // folded.
    dir_items.assign(paths.size(), 0);
    dir_size.assign(paths.size(), 0);
    for (int i = 0; i < static_cast<int>(paths.size()); ++i) {
      if (!counts_as_item(i)) continue;
      const bool dir_row = i < static_cast<int>(is_dir.size()) && is_dir[i];
      const long long size =
          dir_row ? 0 : (i < static_cast<int>(sizes.size()) ? sizes[i] : 0);
      int parent = i < static_cast<int>(parents.size()) ? parents[i] : -1;
      while (parent >= 0) {
        dir_items[parent] += 1;
        dir_size[parent] += size;
        parent = parent < static_cast<int>(parents.size()) ? parents[parent] : -1;
      }
    }
  }

  void compute_stripes() {
    // The Python model stripes every visible row by its position, folders
    // included; do the same here instead of resetting the count per folder.
    stripe.assign(visible.size(), 0);
    for (int row = 0; row < static_cast<int>(visible.size()); ++row) {
      stripe[row] = static_cast<char>(row % 2);
    }
  }

  void set_collapsed(int path_id, bool value) {
    if (path_id >= 0 && path_id < static_cast<int>(collapsed.size())) {
      collapsed[path_id] = value ? 1 : 0;
    }
  }

  bool action_allowed(int id) const {
    if (action_mask == 0) return true;
    if (id < 0 || id >= static_cast<int>(actions.size())) return true;
    const int bit = actions[id];
    return bit >= 0 && bit < 32 && (action_mask & (1 << bit)) != 0;
  }

  bool matches(int id) const {
    if (action_mask == -1) {
      // "Only excluded" mode: only excluded items pass; their ancestor
      // folders are added by rebuild_visible().
      return show_excluded && id < static_cast<int>(decisions.size()) &&
             decisions[id] == Exclude;
    }
    if (action_mask != 0 && id < static_cast<int>(actions.size())) {
      // Directories are filtered too. A filtered directory survives only as
      // the ancestor of a visible row, not merely because it is a folder.
      if (!action_allowed(id)) return false;
    }
    if (dirs_only && (id >= static_cast<int>(is_dir.size()) || !is_dir[id])) {
      return false;
    }
    if (!pattern.empty() && id < static_cast<int>(folded_paths.size())) {
      const bool by_path = pattern.find('/') != std::string::npos;
      const std::string& candidate = by_path ? folded_paths[id] : folded_names[id];
      if (dirs_only && !pattern_glob) {
        const std::string& exact = by_path ? folded_paths[id] : folded_names[id];
        if (exact != pattern) return false;
        return true;
      }
      if (pattern_glob) {
        // Minimal glob: '*' and '?' over the folded candidate.
        const std::string& p = pattern;
        std::size_t ti = 0, pi = 0, star = std::string::npos, mark = 0;
        while (ti < candidate.size()) {
          if (pi < p.size() && (p[pi] == '?' || p[pi] == candidate[ti])) {
            ++pi; ++ti; continue;
          }
          if (pi < p.size() && p[pi] == '*') { star = pi++; mark = ti; continue; }
          if (star != std::string::npos) { pi = star + 1; ti = ++mark; continue; }
          return false;
        }
        while (pi < p.size() && p[pi] == '*') ++pi;
        if (pi != p.size()) return false;
      } else if (candidate.find(pattern) == std::string::npos) {
        return false;
      }
    }
    return true;
  }

  bool folded_out(int id) const {
    int parent = id < static_cast<int>(parents.size()) ? parents[id] : -1;
    while (parent >= 0) {
      if (parent < static_cast<int>(collapsed.size()) && collapsed[parent]) {
        return true;
      }
      parent = parent < static_cast<int>(parents.size()) ? parents[parent] : -1;
    }
    return false;
  }

  std::vector<int> tree_order() const {
    std::vector<std::vector<int>> children(paths.size());
    for (int i = 0; i < static_cast<int>(paths.size()); ++i) {
      int parent = i < static_cast<int>(parents.size()) ? parents[i] : -1;
      if (parent >= 0 && parent < static_cast<int>(children.size())) {
        children[parent].push_back(i);
      }
    }
    int root = -1;
    auto it = path_to_id.find(root_path());
    if (it != path_to_id.end()) root = it->second;
    auto name_less = [&](int a, int b) {
      const std::string& left = a < static_cast<int>(folded_names.size())
                                    ? folded_names[a] : paths[a];
      const std::string& right = b < static_cast<int>(folded_names.size())
                                     ? folded_names[b] : paths[b];
      return sort_desc ? right < left : left < right;
    };
    std::vector<int> order;
    std::function<void(int)> walk = [&](int id) {
      // The Python flat list shows a folder, then that folder's files, then
      // its child folders. Keep the same layout, sorting siblings by name.
      std::vector<int> files = children[id];
      files.erase(
          std::remove_if(files.begin(), files.end(),
                         [&](int child) {
                           return child < static_cast<int>(is_dir.size()) &&
                                  is_dir[child];
                         }),
          files.end());
      std::vector<int> dirs = children[id];
      dirs.erase(
          std::remove_if(dirs.begin(), dirs.end(),
                         [&](int child) {
                           return !(child < static_cast<int>(is_dir.size()) &&
                                    is_dir[child]);
                         }),
          dirs.end());
      std::stable_sort(files.begin(), files.end(), name_less);
      std::stable_sort(dirs.begin(), dirs.end(), name_less);
      order.insert(order.end(), files.begin(), files.end());
      for (int dir : dirs) {
        order.push_back(dir);
        walk(dir);
      }
    };
    if (root >= 0) {
      order.push_back(root);
      walk(root);
    }
    if (order.size() != paths.size()) {
      std::vector<char> seen(paths.size(), 0);
      for (int id : order) seen[id] = 1;
      for (int i = 0; i < static_cast<int>(paths.size()); ++i) {
        if (!seen[i]) order.push_back(i);
      }
    }
    return order;
  }

  void rebuild_visible() {
    visible.clear();
    row_of_id.assign(paths.size(), -1);
    faded.assign(paths.size(), 0);
    std::vector<int> order = tree_order();
    std::vector<char> matched(paths.size(), 0);
    std::vector<char> keep_ancestor(paths.size(), 0);
    for (int i = 0; i < static_cast<int>(paths.size()); ++i) {
      if (!matches(i)) continue;
      if (i < static_cast<int>(is_dir.size()) && is_dir[i] &&
          i < static_cast<int>(actions.size()) && actions[i] == NoChange) {
        continue;
      }
      int parent = i < static_cast<int>(parents.size()) ? parents[i] : -1;
      while (parent >= 0) {
        if (keep_ancestor[parent]) break;
        keep_ancestor[parent] = 1;
        parent = parent < static_cast<int>(parents.size()) ? parents[parent] : -1;
      }
    }
    if (include_contents) {
      for (int i = 0; i < static_cast<int>(paths.size()); ++i) {
        if (is_dir[i] && matches(i)) matched[i] = 1;
      }
      // Ancestors of a matched directory also match, so their children are
      // included when the pattern names a parent folder.
      for (int i = 0; i < static_cast<int>(paths.size()); ++i) {
        if (!matched[i]) continue;
        int parent = parents[i];
        while (parent >= 0) {
          matched[parent] = 1;
          parent = parents[parent];
        }
      }
    }
    int root_id = -1;
    auto root_it = path_to_id.find(root_path());
    if (root_it != path_to_id.end()) root_id = root_it->second;
    if (action_mask == -1 && show_excluded) {
      std::vector<char> keep(paths.size(), 0);
      for (int i = 0; i < static_cast<int>(paths.size()); ++i) {
        if (i >= static_cast<int>(decisions.size()) || decisions[i] != Exclude) continue;
        keep[i] = 1;
        int parent = i < static_cast<int>(parents.size()) ? parents[i] : -1;
        while (parent >= 0) {
          keep[parent] = 1;
          parent = parent < static_cast<int>(parents.size()) ? parents[parent] : -1;
        }
      }
      for (int i : order) {
        if (i != root_id && !keep[i]) continue;
        if (folded_out(i)) continue;
        visible.push_back(i);
      }
      if (sort_column != 0) sort_visible(sort_column, sort_desc);
      for (int row = 0; row < static_cast<int>(visible.size()); ++row) {
        row_of_id[visible[row]] = row;
      }
      compute_aggregates();
      compute_destination_counts();
      compute_stripes();
      return;
    }
    for (int i : order) {
      if (i == root_id) {
        visible.push_back(i);
        continue;
      }
      if (!show_excluded && decisions[i] == Exclude) continue;
      bool path_ok = matches(i);
      if (i < static_cast<int>(is_dir.size()) && is_dir[i] &&
          i < static_cast<int>(actions.size()) && actions[i] == NoChange) {
        path_ok = false;
      }
      if (!path_ok && i < static_cast<int>(keep_ancestor.size()) &&
          keep_ancestor[i]) {
        path_ok = true;
      }
      if (!path_ok && include_contents) {
        int parent = parents[i];
        while (parent >= 0) {
          if (matched[parent]) { path_ok = true; break; }
          parent = parents[parent];
        }
      }
      if (!path_ok) continue;
      if (folded_out(i)) continue;
      visible.push_back(i);
    }
    if (sort_column == 0) {
      // Column 0 keeps the natural folder-tree order built by add_directories().
    } else {
      sort_visible(sort_column, sort_desc);
    }
    for (int row = 0; row < static_cast<int>(visible.size()); ++row) {
      row_of_id[visible[row]] = row;
    }
    faded.assign(paths.size(), 0);
    if (filter_directories) {
      for (int id : visible) {
        if (id < 0 || id >= static_cast<int>(is_dir.size()) || !is_dir[id]) continue;
        if (id >= static_cast<int>(actions.size()) || actions[id] == NoChange) continue;
        if (!action_allowed(id)) faded[id] = 1;
      }
    }
    compute_aggregates();
    compute_destination_counts();
    compute_stripes();
  }

  // Fast path for a single decision edit: update the visible vector without
  // re-sorting half a million rows.
  bool update_single_visibility(int path_id, int decision) {
    if (path_id < 0 || path_id >= static_cast<int>(decisions.size())) return false;
    bool was_hidden = decisions[path_id] == Exclude;
    bool now_hidden = decision == Exclude;
    decisions[path_id] = decision;
    if (was_hidden == now_hidden) return false;
    if (sort_column != 0 || !pattern.empty()) return false;
    int row = row_of_id[path_id];
    if (now_hidden) {
      if (row < 0) return false;
      visible.erase(visible.begin() + row);
    } else {
      // `visible` is in tree order, not lexicographic order; inserting by
      // path made restored rows appear at a random place. Rebuild instead.
      rebuild_visible();
      compute_destination_counts();
      return true;
    }
    for (int r = row; r < static_cast<int>(visible.size()); ++r) {
      row_of_id[visible[r]] = r;
    }
    compute_stripes();
    return true;
  }

  std::vector<int> search(const std::string& text) const {
    std::vector<int> result;
    for (int row = 0; row < static_cast<int>(visible.size()); ++row) {
      int id = visible[row];
      if (id < static_cast<int>(folded_names.size()) &&
          folded_names[id].find(text) != std::string::npos) {
        result.push_back(row);
      }
    }
    return result;
  }

  void sort_by(int column) {
    std::stable_sort(visible.begin(), visible.end(), [&](int a, int b) {
      if (column == 1) return actions[a] < actions[b];
      if (column == 2) return sizes[a] < sizes[b];
      return paths[a] < paths[b];
    });
  }

  void apply_filter() {
    visible.clear();
    for (int i = 0; i < static_cast<int>(decisions.size()); ++i) {
      if (show_excluded || decisions[i] != Exclude) visible.push_back(i);
    }
  }

  void set_decision_id(int id, int decision, bool subtree = false) {
    if (id < 0 || id >= static_cast<int>(decisions.size())) return;
    decisions[id] = decision;
    decision_log.emplace_back(id, decision);
    if (!subtree || id >= static_cast<int>(is_dir.size()) || !is_dir[id]) return;
    const std::string prefix = paths[id] + "/";
    for (int i = 0; i < static_cast<int>(paths.size()); ++i) {
      if (paths[i].compare(0, prefix.size(), prefix) != 0) continue;
      if (decisions[i] == decision) continue;
      decisions[i] = decision;
      decision_log.emplace_back(i, decision);
    }
  }

  void toggle_decision(int path_id, bool subtree = false) {
    if (path_id < 0 || path_id >= static_cast<int>(decisions.size())) return;
    const int next = decisions[path_id] == Exclude ||
                             decisions[path_id] == DeleteRequest
                         ? Inherit
                         : Exclude;
    set_decision_id(path_id, next, subtree);
  }

  void sort_visible(int column, bool descending) {
    const bool by_name = column == 0 || column == 5;
    if (by_name) return;  // name keeps the folder-tree order built in tree_order()
    auto dir_flag = [&](int id) {
      return id < static_cast<int>(is_dir.size()) && is_dir[id] != 0;
    };
    auto name_of = [&](int id) -> const std::string& {
      return id < static_cast<int>(folded_names.size()) ? folded_names[id]
                                                       : paths[id];
    };
    static const int action_rank[] = {0, 5, 3, 1, 2, 4, 6};
    struct SortKey {
      long long number;
      std::string text;
    };
    std::vector<SortKey> keys(visible.size());
    for (std::size_t i = 0; i < visible.size(); ++i) {
      const int id = visible[i];
      SortKey& key = keys[i];
      if (column == 1 || column == 6) {
        key.number = dir_flag(id) && id < static_cast<int>(dir_items.size())
                         ? dir_items[id] : 0;
        key.text = name_of(id);
      } else if (column == 3 || column == 8) {
        key.number = 0;
        key.text = id < static_cast<int>(times.size()) ? times[id] : std::string();
      } else if (column == 4) {
        if (dir_flag(id)) {
          key.number = -1;
        } else {
          const int code = id < static_cast<int>(actions.size()) ? actions[id] : 5;
          key.number = code >= 0 && code < 7 ? action_rank[code] : 6;
        }
        key.text = name_of(id);
      } else {
        key.number = dir_flag(id) && id < static_cast<int>(dir_size.size())
                         ? dir_size[id]
                         : (id < static_cast<int>(sizes.size()) ? sizes[id] : 0);
        key.text = name_of(id);
      }
    }
    std::vector<int> order(visible.size());
    std::iota(order.begin(), order.end(), 0);
    std::stable_sort(order.begin(), order.end(), [&](int a, int b) {
      const SortKey& left = keys[a];
      const SortKey& right = keys[b];
      if (left.number != right.number) {
        return descending ? left.number > right.number
                          : left.number < right.number;
      }
      if (left.text != right.text) {
        return descending ? left.text > right.text : left.text < right.text;
      }
      return paths[visible[a]] < paths[visible[b]];
    });
    std::vector<int> sorted;
    sorted.reserve(visible.size());
    int root_id = -1;
    auto root_it = path_to_id.find(root_path());
    if (root_it != path_to_id.end()) root_id = root_it->second;
    for (int index : order) {
      if (visible[index] != root_id) sorted.push_back(visible[index]);
    }
    visible.clear();
    if (root_id >= 0) visible.push_back(root_id);
    visible.insert(visible.end(), sorted.begin(), sorted.end());
  }

};

class TableModel : public QAbstractTableModel {
 public:
  TableModel(DataStore* store, int pane, QObject* parent = nullptr)
      : QAbstractTableModel(parent), store_(store), pane_(pane) {}

  int rowCount(const QModelIndex& parent = QModelIndex()) const override {
    return parent.isValid() ? 0 : static_cast<int>(store_->visible.size());
  }

  int columnCount(const QModelIndex& parent = QModelIndex()) const override {
    return parent.isValid() ? 0 : 11;
  }

  QVariant data(const QModelIndex& index, int role = Qt::DisplayRole) const override {
    if (!index.isValid()) return {};
    int row = index.row();
    if (row < 0 || row >= static_cast<int>(store_->visible.size())) return {};
    int id = store_->visible[row];
    if (role == Qt::CheckStateRole) {
      if (pane_ == 1 && index.column() == 4) {
        // The compared folder is the container: it has no exclude checkbox.
        if (store_->paths[id] == DataStore::root_path()) return {};
        // A delete decision is shown by the red marker alone; a checkbox
        // here looked disabled and clicking it created an Exclude decision.
        if (id < static_cast<int>(store_->decisions.size()) &&
            store_->decisions[id] == DeleteRequest) {
          return {};
        }
        return store_->decisions[id] == Exclude ? Qt::Unchecked : Qt::Checked;
      }
      return {};
    }
    if (role == Qt::ToolTipRole) {
      const std::string& path = id < static_cast<int>(store_->paths.size())
                                    ? store_->paths[id] : std::string();
      if (path == DataStore::root_path()) return QString("Compared folder");
      const QString shown = QString::fromStdString(path);
      if (index.column() == 4) {
        int action = id < static_cast<int>(store_->actions.size())
                         ? store_->actions[id] : NoChange;
        if (id < static_cast<int>(store_->decisions.size()) &&
            store_->decisions[id] == DeleteRequest) {
          action = Delete;
        }
        QString tip = "Source: " + shown + "\nDestination: " + shown +
                      "\n" + QString::fromStdString(action_label(action));
        const std::string time = id < static_cast<int>(store_->times.size())
                                     ? store_->times[id] : std::string();
        if (!time.empty()) tip += "\nModified: " + QString::fromStdString(time);
        return tip;
      }
      return shown;
    }
    if (role == Qt::ForegroundRole) {
      if (pane_ == 1) return {};
      int action = id < static_cast<int>(store_->actions.size())
                       ? store_->actions[id] : NoChange;
      if (id < static_cast<int>(store_->decisions.size()) &&
          store_->decisions[id] == DeleteRequest) {
        action = Delete;
      }
      if (action >= 0 && action < static_cast<int>(store_->action_colours.size())) {
        const QString hex = store_->action_colours[action];
        if (!hex.isEmpty()) return QColor(hex);
      }
      if (id < static_cast<int>(store_->decisions.size()) &&
          store_->decisions[id] == Exclude) {
        return QColor("#9CA3AF");
      }
      return {};
    }
    if (role != Qt::DisplayRole) return {};
    const int column = index.column();
    const int action = id < static_cast<int>(store_->actions.size())
                           ? store_->actions[id] : NoChange;
    const bool source_present = action != DestOnly && action != Delete;
    const bool dest_present = action != Create;
    if ((pane_ == 0 && !source_present) || (pane_ == 2 && !dest_present)) {
      return {};
    }
    const std::string& path = store_->paths[id];
    const std::string time = id < static_cast<int>(store_->times.size())
                                 ? store_->times[id] : std::string();
    const bool is_dir = id < static_cast<int>(store_->is_dir.size()) && store_->is_dir[id];
    const bool is_root = path == DataStore::root_path();
    // Folders keep their name and icon on both sides. Only their counts and
    // sizes are blank when that side has no items below the folder.
    if (is_dir && !is_root) {
      if (pane_ == 0 && (column == 1 || column == 2 || column == 9)) {
        const long long owned = id < static_cast<int>(store_->dir_items.size())
                                    ? store_->dir_items[id] : 0;
        if (owned == 0) return {};
      }
      if (pane_ == 2 && (column == 6 || column == 7 || column == 10)) {
        const long long owned = id < static_cast<int>(store_->dest_items.size())
                                    ? store_->dest_items[id] : 0;
        if (owned == 0) return {};
      }
    }
    if (column == 0 || column == 5) {
      if (is_root) {
        return QString::fromStdString(pane_ == 0 ? store_->root_source : store_->root_dest);
      }
      return QString::fromStdString(
          id < static_cast<int>(store_->names.size()) ? store_->names[id] : path);
    }
    if (column == 1) {
      if (is_dir && id < static_cast<int>(store_->dir_items.size())) {
        return QVariant(static_cast<qlonglong>(store_->dir_items[id]));
      }
      return {};
    }
    if (column == 6) {
      if (is_dir && id < static_cast<int>(store_->dest_items.size())) {
        return QVariant(static_cast<qlonglong>(store_->dest_items[id]));
      }
      return {};
    }
    if (column == 2) {
      long long size = (is_dir && id < static_cast<int>(store_->dir_size.size()))
                           ? store_->dir_size[id]
                           : (id < static_cast<int>(store_->sizes.size())
                                  ? store_->sizes[id] : 0);
      return qpy_format_size(size);
    }
    if (column == 7 || column == 10) {
      long long size = id < static_cast<int>(store_->dest_sizes.size())
                           ? store_->dest_sizes[id] : 0;
      if (size == 0 && !is_dir) return QString();
      return qpy_format_size(size);
    }
    if (column == 3) return QString::fromStdString(time);
    if (column == 8) {
      return id < static_cast<int>(store_->dest_times.size())
                 ? QString::fromStdString(store_->dest_times[id]) : QString();
    }
    if (column == 9) {
      return QVariant(static_cast<qlonglong>(
          id < static_cast<int>(store_->sizes.size()) ? store_->sizes[id] : 0));
    }
    if (column == 4) {
      int shown_action = store_->actions[id];
      if (id < static_cast<int>(store_->decisions.size()) &&
          store_->decisions[id] == DeleteRequest) {
        shown_action = Delete;
      }
      return QString::fromStdString(action_label(shown_action));
    }
    return {};
  }

  QVariant headerData(int section, Qt::Orientation, int role) const override {
    if (role != Qt::DisplayRole) return {};
    static const char* headers[11] = {
        "Item", "Items", "Size", "Modified", "Decisions",
        "Item", "Items", "Size", "Modified", "Size (bytes)", "Size (bytes)"};
    return section >= 0 && section < 11 ? QString(headers[section]) : QString();
  }

  void sort(int column, Qt::SortOrder order = Qt::AscendingOrder) override {
    store_->sort_column = column;
    store_->sort_desc = order == Qt::DescendingOrder;
    store_->rebuild_visible();
    reset();
  }

  void reset() {
    beginResetModel();
    endResetModel();
  }

  void layout_refresh() { emit layoutChanged(); }

  Qt::ItemFlags flags(const QModelIndex& index) const override {
    if (pane_ == 1 && index.column() == 4 && index.isValid()) {
      const int id = store_->visible[index.row()];
      if (store_->paths[id] == DataStore::root_path()) {
        return Qt::ItemIsEnabled | Qt::ItemIsSelectable;
      }
      if (id >= 0 && id < static_cast<int>(store_->decisions.size()) &&
          store_->decisions[id] == DeleteRequest) {
        return Qt::ItemIsEnabled | Qt::ItemIsSelectable;
      }
      return Qt::ItemIsEnabled | Qt::ItemIsSelectable | Qt::ItemIsUserCheckable;
    }
    return QAbstractTableModel::flags(index);
  }

  bool setData(const QModelIndex& index, const QVariant& value,
               int role = Qt::EditRole) override {
    if (pane_ != 1 || index.column() != 4 || role != Qt::CheckStateRole) {
      return false;
    }
    int row = index.row();
    if (row < 0 || row >= static_cast<int>(store_->visible.size())) return false;
    int path_id = store_->visible[row];
    if (store_->paths[path_id] == DataStore::root_path()) return false;
    store_->toggle_decision(path_id, true);
    store_->rebuild_visible();
    if (g_decision_hook != nullptr) {
      g_decision_hook(path_id, store_->decisions[path_id]);
    }
    emit dataChanged(index, index, {Qt::CheckStateRole, Qt::DisplayRole});
    return true;
  }

 private:
  static std::string action_label(int action) {
    switch (action) {
      case Create: return "new";
      case Update: return "updated";
      case Metadata: return "metadata";
      case Delete: return "delete";
      case DestOnly: return "destination only";
      default: return "unchanged";
    }
  }

  static QString action_name(int action) {
    switch (action) {
      case Create: return QString("new");
      case Update: return QString("updated");
      case Metadata: return QString("metadata");
      case Delete: return QString("delete");
      case DestOnly: return QString("destination only");
      default: return QString("unchanged");
    }
  }

  DataStore* store_;
  int pane_;
};


struct OverviewNode {
  std::string name;
  std::string path;
  int count = 0;
  long long size = 0;
  long long total_count = 0;
  long long total_size = 0;
  OverviewNode* parent = nullptr;
  std::vector<OverviewNode*> children;
};

class OverviewModel : public QAbstractItemModel {
 public:
  explicit OverviewModel(QObject* parent = nullptr) : QAbstractItemModel(parent) {
    root_ = new OverviewNode{"", "", 0, 0, 0, 0, nullptr, {}};
    nodes_.push_back(root_);
  }

  ~OverviewModel() override {
    for (OverviewNode* node : nodes_) delete node;
  }

  void build(const DataStore& store, bool visible_only = false) {
    beginResetModel();
    for (OverviewNode* node : nodes_) delete node;
    nodes_.clear();
    root_ = new OverviewNode{"", "", 0, 0, 0, 0, nullptr, {}};
    nodes_.push_back(root_);
    auto* total = new OverviewNode{"Total", "", 0, 0, 0, 0, root_, {}};
    root_->children.push_back(total);
    nodes_.push_back(total);

    // Build the same hierarchy as the Python overview: folders nested by
    // path, with a "Files" child holding the direct files of each folder.
    std::unordered_map<std::string, OverviewNode*> folders;
    auto add_child = [&](OverviewNode* parent, const std::string& name,
                         const std::string& path) {
      auto* node = new OverviewNode{name, path, 0, 0, 0, 0, parent, {}};
      parent->children.push_back(node);
      nodes_.push_back(node);
      return node;
    };
    auto ensure_folder = [&](const std::string& path) {
      auto found = folders.find(path);
      if (found != folders.end()) return found->second;
      OverviewNode* parent = total;
      std::string prefix;
      std::size_t begin = 0;
      while (begin < path.size()) {
        const std::size_t slash = path.find('/', begin);
        const std::string part = slash == std::string::npos
                                     ? path.substr(begin)
                                     : path.substr(begin, slash - begin);
        prefix = prefix.empty() ? part : prefix + "/" + part;
        auto it = folders.find(prefix);
        if (it == folders.end()) {
          it = folders.emplace(prefix, add_child(parent, part, prefix)).first;
        }
        parent = it->second;
        if (slash == std::string::npos) break;
        begin = slash + 1;
      }
      return parent;
    };

    auto consider = [&](int i) {
      if (i < 0 || i >= static_cast<int>(store.paths.size())) return;
      const std::string& path = store.paths[i];
      if (path == DataStore::root_path() || path.empty()) return;
      if (!store.counts_as_item(i)) return;
      const bool dir_row = i < static_cast<int>(store.is_dir.size()) && store.is_dir[i];
      const std::size_t slash = path.rfind('/');
      const std::string folder_path = slash == std::string::npos
                                          ? "" : path.substr(0, slash);
      // Direct objects live in the folder's synthetic "Files" row. A reported
      // directory is an object of its parent, so its node is created for its
      // contents but it is counted in the parent.
      if (dir_row) ensure_folder(path);
      OverviewNode* folder = folder_path.empty() ? total : ensure_folder(folder_path);
      OverviewNode* files = nullptr;
      for (OverviewNode* child : folder->children) {
        if (child->name == "Files") { files = child; break; }
      }
      if (files == nullptr) files = add_child(folder, "Files", "");
      ++files->count;
      if (!dir_row) {
        files->size += i < static_cast<int>(store.sizes.size()) ? store.sizes[i] : 0;
      }
    };
    if (visible_only) {
      for (int id : store.visible) consider(id);
    } else {
      for (int i = 0; i < static_cast<int>(store.paths.size()); ++i) consider(i);
    }
    std::function<void(OverviewNode*)> sort_children = [&](OverviewNode* node) {
      std::sort(node->children.begin(), node->children.end(),
                [](const OverviewNode* a, const OverviewNode* b) {
                  if (a->size != b->size) return a->size > b->size;
                  return a->name < b->name;
                });
      for (OverviewNode* child : node->children) sort_children(child);
    };
    sort_children(root_);
    compute_totals(root_);
    // The Total row carries the aggregate of the whole comparison.
    total->total_count = root_->total_count;
    total->total_size = root_->total_size;
    grand_total_ = root_->total_count > 0 ? root_->total_count : 1;
    endResetModel();
  }

  void sort(int column, Qt::SortOrder order = Qt::AscendingOrder) override {
    const bool descending = order == Qt::DescendingOrder;
    if (root_ == nullptr || root_->children.empty()) return;
    layoutAboutToBeChanged();
    std::function<void(OverviewNode*)> sort_children = [&](OverviewNode* node) {
      std::stable_sort(node->children.begin(), node->children.end(),
                       [column, descending](OverviewNode* a, OverviewNode* b) {
                         int comparison = 0;
                         switch (column) {
                           case 0:
                             comparison = QString::fromStdString(a->name)
                                              .compare(QString::fromStdString(b->name),
                                                      Qt::CaseInsensitive);
                             break;
                           case 1:
                           case 3:
                             comparison = (a->total_size > b->total_size) -
                                          (a->total_size < b->total_size);
                             break;
                           case 2:
                             comparison = (a->total_count > b->total_count) -
                                          (a->total_count < b->total_count);
                             break;
                           default:
                             break;
                         }
                         if (comparison == 0) {
                           comparison = QString::fromStdString(a->name).compare(
                               QString::fromStdString(b->name),
                               Qt::CaseInsensitive);
                         }
                         return descending ? comparison > 0 : comparison < 0;
                       });
      for (OverviewNode* child : node->children) sort_children(child);
    };
    sort_children(root_);
    layoutChanged();
  }

  QModelIndex index_for_path(const std::string& path) const {
    for (OverviewNode* node : nodes_) {
      if (node->path != path || node == root_) continue;
      OverviewNode* parent = node->parent;
      if (parent == nullptr) return {};
      // Find this node's row among its parent's children.
      int row = 0;
      for (OverviewNode* child : parent->children) {
        if (child == node) {
          QModelIndex parent_index = parent == root_
                                         ? QModelIndex()
                                         : index_for_path(parent->path);
          return index(row, 0, parent_index);
        }
        ++row;
      }
    }
    return {};
  }

  int rowCount(const QModelIndex& parent = QModelIndex()) const override {
    if (parent.isValid() && parent.column() != 0) return 0;
    return static_cast<int>(node(parent)->children.size());
  }

  int columnCount(const QModelIndex&) const override { return 4; }

  QModelIndex index(int row, int column,
                    const QModelIndex& parent = QModelIndex()) const override {
    if (!hasIndex(row, column, parent)) return {};
    auto* node = node_at(parent)->children[row];
    return createIndex(row, column, node);
  }

  QModelIndex parent(const QModelIndex& index) const override {
    if (!index.isValid()) return {};
    OverviewNode* parent = node(index)->parent;
    if (!parent || parent == root_) return {};
    OverviewNode* grandparent = parent->parent;
    int row = 0;
    for (OverviewNode* child : grandparent->children) {
      if (child == parent) break;
      ++row;
    }
    return createIndex(row, 0, parent);
  }

  QVariant headerData(int section, Qt::Orientation, int role) const override {
    if (role != Qt::DisplayRole) return {};
    static const char* headers[4] = {"Item", "Share", "Items", "Size"};
    return section >= 0 && section < 4 ? QString(headers[section]) : QString();
  }

  QVariant data(const QModelIndex& index, int role = Qt::DisplayRole) const override {
    if (!index.isValid()) return {};
    OverviewNode* item = node(index);
    if (role == Qt::UserRole) return QString::fromStdString(item->path);
    if (role == Qt::UserRole + 20) {
      // Share of this node among its siblings, by size (like the Python view).
      long long siblings = 0;
      if (item->parent != nullptr) {
        for (OverviewNode* child : item->parent->children) {
          siblings += child->total_size;
        }
      }
      return siblings > 0
                 ? static_cast<double>(item->total_size) / static_cast<double>(siblings)
                 : 0.0;
    }
    if (role == Qt::TextAlignmentRole) {
      return static_cast<int>(Qt::AlignLeft | Qt::AlignVCenter);
    }
    if (role != Qt::DisplayRole) return {};
    switch (index.column()) {
      case 0: return QString::fromStdString(item->name);
      case 1: {
        long long siblings = 0;
        if (item->parent != nullptr) {
          for (OverviewNode* child : item->parent->children) {
            siblings += child->total_size;
          }
        }
        const double share = siblings > 0
                                 ? static_cast<double>(item->total_size) /
                                       static_cast<double>(siblings)
                                 : 0.0;
        return QString::number(static_cast<int>(share * 100.0 + 0.5)) + "%";
      }
      case 2: return QVariant(static_cast<qlonglong>(item->total_count));
      case 3: return qpy_format_size(item->total_size);
    }
    return {};
  }

 private:
  static void compute_totals(OverviewNode* node) {
    for (OverviewNode* child : node->children) compute_totals(child);
    node->total_count = node->count;
    node->total_size = node->size;
    for (OverviewNode* child : node->children) {
      node->total_count += child->total_count;
      node->total_size += child->total_size;
    }
  }

  OverviewNode* node(const QModelIndex& index) const {
    return index.isValid() ? static_cast<OverviewNode*>(index.internalPointer())
                           : root_;
  }
  OverviewNode* node_at(const QModelIndex& index) const { return node(index); }

  std::vector<OverviewNode*> nodes_;
  OverviewNode* root_ = nullptr;
  long long grand_total_ = 1;
};

#endif  // QPY_NATIVE_QT_MODEL_HPP
