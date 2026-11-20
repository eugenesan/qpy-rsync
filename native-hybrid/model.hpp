// Shared data store and Qt models for the native Qt model experiment.
#ifndef QPY_NATIVE_QT_MODEL_HPP
#define QPY_NATIVE_QT_MODEL_HPP

#include <QAbstractItemModel>
#include <QAbstractTableModel>
#include <QElapsedTimer>
#include <QVariant>
#include <QAbstractItemModel>

#include <algorithm>
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
enum Decision { Inherit = 0, Include = 1, Exclude = 2 };

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
    visible.resize(count);
    std::iota(visible.begin(), visible.end(), 0);
    *parse_ms = timer.elapsed();
    return true;
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
    folded_names.resize(count);
    folded_paths.resize(count);
    path_to_id.clear();
    for (int i = 0; i < count; ++i) path_to_id[paths[i]] = i;
    for (int i = 0; i < count; ++i) {
      const std::string& path = paths[i];
      std::size_t slash = path.rfind('/');
      parents[i] = -1;
      if (slash != std::string::npos) {
        auto parent_it = path_to_id.find(path.substr(0, slash));
        if (parent_it != path_to_id.end()) parents[i] = parent_it->second;
      }
      is_dir[i] = !path.empty() && path.back() == '/' ? 1 : 0;
      std::string name = slash == std::string::npos
                             ? path
                             : path.substr(slash + 1);
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
    decision_log.clear();
    collapsed.assign(paths.size(), 0);
    action_mask = 0;
    pattern.clear();
    sort_column = 0;
    sort_desc = false;
    visible.resize(paths.size());
    std::iota(visible.begin(), visible.end(), 0);
  }

  void set_collapsed(int path_id, bool value) {
    if (path_id >= 0 && path_id < static_cast<int>(collapsed.size())) {
      collapsed[path_id] = value ? 1 : 0;
    }
  }

  bool matches(int id) const {
    if (action_mask != 0 && id < static_cast<int>(actions.size())) {
      int bit = actions[id];
      if (bit < 0 || bit >= 32 || (action_mask & (1 << bit)) == 0) return false;
    }
    if (!pattern.empty() && id < static_cast<int>(folded_paths.size())) {
      const std::string& candidate =
          pattern.find('/') != std::string::npos ? folded_paths[id]
                                                  : folded_names[id];
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

  void rebuild_visible() {
    visible.clear();
    row_of_id.assign(paths.size(), -1);
    for (int i = 0; i < static_cast<int>(paths.size()); ++i) {
      if (!show_excluded && decisions[i] == Exclude) continue;
      if (!matches(i)) continue;
      if (folded_out(i)) continue;
      visible.push_back(i);
    }
    if (sort_column == 0) {
      std::stable_sort(visible.begin(), visible.end(), [&](int a, int b) {
        return paths[a] < paths[b];
      });
    } else if (sort_column == 1) {
      std::stable_sort(visible.begin(), visible.end(), [&](int a, int b) {
        return actions[a] < actions[b];
      });
    } else {
      std::stable_sort(visible.begin(), visible.end(), [&](int a, int b) {
        return sizes[a] < sizes[b];
      });
    }
    if (sort_desc) std::reverse(visible.begin(), visible.end());
    for (int row = 0; row < static_cast<int>(visible.size()); ++row) {
      row_of_id[visible[row]] = row;
    }
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

  void toggle_decision(int path_id) {
    if (path_id < 0 || path_id >= static_cast<int>(decisions.size())) return;
    int next = decisions[path_id] == Exclude ? Inherit : Exclude;
    decisions[path_id] = next;
    decision_log.emplace_back(path_id, next);
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
    return parent.isValid() ? 0 : 3;
  }

  QVariant data(const QModelIndex& index, int role = Qt::DisplayRole) const override {
    if (!index.isValid()) return {};
    if (role == Qt::CheckStateRole) {
      if (pane_ == 1 && index.column() == 1) {
        int row = index.row();
        if (row < 0 || row >= static_cast<int>(store_->visible.size())) return {};
        int path_id = store_->visible[row];
        return store_->decisions[path_id] == Exclude
                   ? Qt::Unchecked : Qt::Checked;
      }
      return {};
    }
    if (role != Qt::DisplayRole) return {};
    const int row = index.row();
    if (row < 0 || row >= static_cast<int>(store_->visible.size())) return {};
    const int record = store_->visible[row];
    const int column = index.column();
    if (pane_ == 0) {  // Source: name, size, modified
      if (column == 0) return QString::fromStdString(store_->paths[record]);
      if (column == 1) return QString::number(store_->sizes[record]);
      return QString::fromStdString(
          record < static_cast<int>(store_->times.size())
              ? store_->times[record] : std::string());
    }
    if (pane_ == 1) {  // Action: action, decision, reason
      if (column == 0) return action_name(store_->actions[record]);
      if (column == 1) {
        return store_->decisions[record] == Exclude
                   ? QString("excluded") : QString("included");
      }
      return QString("selection");
    }
    // Destination: path, size, modified (same values until metadata is handed over).
    if (column == 0) return QString::fromStdString(store_->paths[record]);
    if (column == 1) return QString::number(store_->sizes[record]);
    return QString::fromStdString(
        record < static_cast<int>(store_->times.size())
            ? store_->times[record] : std::string());
  }

  QVariant headerData(int section, Qt::Orientation, int role) const override {
    if (role != Qt::DisplayRole) return {};
    if (pane_ == 0) {
      return section == 0 ? QString("Name")
                          : (section == 1 ? QString("Size") : QString("Modified"));
    }
    if (pane_ == 1) {
      return section == 0 ? QString("Action")
                          : (section == 1 ? QString("Decision") : QString("Reason"));
    }
    return section == 0 ? QString("Path")
                        : (section == 1 ? QString("Size") : QString("Modified"));
  }

  void reset() {
    beginResetModel();
    endResetModel();
  }

  Qt::ItemFlags flags(const QModelIndex& index) const override {
    if (pane_ == 1 && index.column() == 1 && index.isValid()) {
      return Qt::ItemIsEnabled | Qt::ItemIsSelectable | Qt::ItemIsUserCheckable;
    }
    return QAbstractTableModel::flags(index);
  }

  bool setData(const QModelIndex& index, const QVariant& value,
               int role = Qt::EditRole) override {
    if (pane_ != 1 || index.column() != 1 || role != Qt::CheckStateRole) {
      return false;
    }
    int row = index.row();
    if (row < 0 || row >= static_cast<int>(store_->visible.size())) return false;
    int path_id = store_->visible[row];
    store_->toggle_decision(path_id);
    if (g_decision_hook != nullptr) {
      g_decision_hook(path_id, store_->decisions[path_id]);
    }
    emit dataChanged(index, index, {Qt::CheckStateRole, Qt::DisplayRole});
    return true;
  }

 private:
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
    root_ = new OverviewNode{"", 0, 0, 0, 0, nullptr, {}};
    nodes_.push_back(root_);
  }

  ~OverviewModel() override {
    for (OverviewNode* node : nodes_) delete node;
  }

  void build(const DataStore& store) {
    beginResetModel();
    for (OverviewNode* node : nodes_) delete node;
    nodes_.clear();
    root_ = new OverviewNode{"", 0, 0, 0, 0, nullptr, {}};
    nodes_.push_back(root_);
    auto* total = new OverviewNode{"Total", 0, 0, 0, 0, root_, {}};
    root_->children.push_back(total);
    nodes_.push_back(total);
    auto* base = new OverviewNode{"All folders", 0, 0, 0, 0, total, {}};
    total->children.push_back(base);
    nodes_.push_back(base);

    // One folder node per distinct first path component, as the real
    // overview does for its 30k folders.
    std::unordered_map<std::string, OverviewNode*> folders;
    for (int i = 0; i < static_cast<int>(store.paths.size()); ++i) {
      const std::string& path = store.paths[i];
      auto slash = path.find('/');
      if (slash == std::string::npos) continue;
      std::string name = path.substr(0, slash);
      if (name.empty()) continue;
      OverviewNode*& folder = folders[name];
      if (folder == nullptr) {
        folder = new OverviewNode{name, 0, 0, 0, 0, base, {}};
        base->children.push_back(folder);
        nodes_.push_back(folder);
      }
      ++folder->count;
      folder->size += store.sizes[i];
    }
    compute_totals(root_);
    endResetModel();
  }

  int rowCount(const QModelIndex& parent = QModelIndex()) const override {
    if (parent.isValid() && parent.column() != 0) return 0;
    return static_cast<int>(node(parent)->children.size());
  }

  int columnCount(const QModelIndex&) const override { return 3; }

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

  QVariant data(const QModelIndex& index, int role = Qt::DisplayRole) const override {
    if (!index.isValid() || role != Qt::DisplayRole) return {};
    OverviewNode* item = node(index);
    if (index.column() == 0) return QString::fromStdString(item->name);
    if (index.column() == 1) return QString::number(item->total_count);
    return QString::number(item->total_size);
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
};

#endif  // QPY_NATIVE_QT_MODEL_HPP
