// Shared data store and Qt models for the native Qt model experiment.
#ifndef QPY_NATIVE_QT_MODEL_HPP
#define QPY_NATIVE_QT_MODEL_HPP

#include <QAbstractItemModel>
#include <QAbstractTableModel>
#include <QElapsedTimer>
#include <QVariant>
#include <QAbstractItemModel>

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <numeric>
#include <string>
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
  std::vector<int> sizes;
  std::vector<int> decisions;
  // Stable decision key: row positions are volatile after sort/filter.
  std::vector<std::pair<int, int>> decision_log;
  std::vector<int> visible;
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
                   const std::vector<int>& decisions_) {
    paths = paths_;
    actions = actions_;
    kinds = kinds_;
    sizes.assign(sizes_.begin(), sizes_.end());
    decisions = decisions_;
    decision_log.clear();
    visible.resize(paths.size());
    std::iota(visible.begin(), visible.end(), 0);
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
    if (pane_ == 0) return QString::fromStdString(store_->paths[record]);
    if (pane_ == 1) {
      if (index.column() == 0) return action_name(store_->actions[record]);
      return store_->actions[record] == Delete ? QString("delete") : QString("keep");
    }
    if (index.column() == 1) return QString::number(store_->sizes[record]);
    return store_->decisions[record] == Exclude ? QString("excluded") : QString("included");
  }

  QVariant headerData(int section, Qt::Orientation, int role) const override {
    if (role != Qt::DisplayRole) return {};
    if (pane_ == 0) return section == 0 ? QString("Name") : QString("Size");
    if (pane_ == 1) return section == 0 ? QString("Action") : QString("Decision");
    return section == 0 ? QString("Destination") : QString("Date");
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
  int size = 0;
  int total_count = 0;
  int total_size = 0;
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
    auto* base = new OverviewNode{"source", 0, 0, 0, 0, total, {}};
    total->children.push_back(base);
    nodes_.push_back(base);

    // One folder node per distinct first path component, as the real
    // overview does for its 30k folders.
    std::vector<OverviewNode*> folders(30000, nullptr);
    for (int i = 0; i < static_cast<int>(store.paths.size()); ++i) {
      const std::string& path = store.paths[i];
      auto slash = path.find('/');
      if (slash == std::string::npos) continue;
      int id = std::atoi(path.c_str() + 1);
      if (id < 0 || id >= 30000) continue;
      OverviewNode*& folder = folders[id];
      if (folder == nullptr) {
        folder = new OverviewNode{path.substr(0, slash), 0, 0, 0, 0, base, {}};
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
