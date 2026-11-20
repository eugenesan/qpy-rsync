// Standalone experiment: can native Qt models handle a million-row,
// three-pane comparison view? No Python and no rsync in this phase; the data
// is generated locally so the measurement is the ceiling of a C++ port.

#include <QAbstractTableModel>
#include <QApplication>
#include <QElapsedTimer>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QString>
#include <QTableView>
#include <QTreeView>
#include <QVariant>
#include <QWidget>

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <numeric>
#include <random>
#include <string>
#include <utility>
#include <vector>

namespace {

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
    if (!index.isValid() || role != Qt::DisplayRole) return {};
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

void report(const char* label, qint64 ms) {
  std::printf("%-34s %10lld ms\n", label, static_cast<long long>(ms));
}

long rss_kb() {
  FILE* f = std::fopen("/proc/self/statm", "r");
  if (!f) return 0;
  long total = 0, resident = 0;
  if (std::fscanf(f, "%ld %ld", &total, &resident) != 2) resident = 0;
  std::fclose(f);
  return resident * 4;  // Linux pages are usually 4 KiB
}

}  // namespace

int main(int argc, char** argv) {
  int count = 1000000;
  for (int i = 1; i < argc; ++i) {
    std::string arg = argv[i];
    if (arg.rfind("--items=", 0) == 0) count = std::atoi(arg.c_str() + 8);
  }

  QApplication app(argc, argv);
  QElapsedTimer timer;

  DataStore store;
  timer.start();
  store.generate(count);
  report("store.generate", timer.elapsed());

  TableModel source(&store, 0);
  TableModel action(&store, 1);
  TableModel destination(&store, 2);
  report("models.create", 0);

  QWidget window;
  auto* layout = new QHBoxLayout(&window);
  QTableView views[3];
  for (int i = 0; i < 3; ++i) {
    views[i].verticalHeader()->setDefaultSectionSize(22);
    views[i].verticalHeader()->hide();
    views[i].horizontalHeader()->setStretchLastSection(true);
    layout->addWidget(&views[i]);
  }
  QTreeView overview_view;
  overview_view.setUniformRowHeights(true);
  overview_view.header()->setStretchLastSection(true);
  layout->addWidget(&overview_view);
  OverviewModel overview_model;
  timer.start();
  views[0].setModel(&source);
  views[1].setModel(&action);
  views[2].setModel(&destination);
  timer.start();
  overview_model.build(store);
  report("overview.build (30k folders)", timer.elapsed());
  timer.start();
  overview_view.setModel(&overview_model);
  overview_view.expandToDepth(0);
  window.resize(1600, 800);
  window.show();
  app.processEvents();
  app.processEvents();
  report("first paint (3 views, processEvents)", timer.elapsed());

  timer.start();
  store.sort_by(2);
  source.reset(); action.reset(); destination.reset();
  app.processEvents();
  report("sort by size + reset + paint", timer.elapsed());

  timer.start();
  store.show_excluded = true;
  store.apply_filter();
  source.reset(); action.reset(); destination.reset();
  app.processEvents();
  report("filter (show excluded) + paint", timer.elapsed());

  std::mt19937 rng(7);
  timer.start();
  for (int i = 0; i < 1000; ++i) {
    int id = static_cast<int>(rng() % static_cast<unsigned>(count));
    store.toggle_decision(id);
  }
  report("1000 decision toggles (no UI update)", timer.elapsed());

  timer.start();
  source.reset(); action.reset(); destination.reset();
  app.processEvents();
  report("repaint after decision batch", timer.elapsed());

  timer.start();
  std::vector<std::pair<int, int>> diff = store.decision_log;
  report("diff snapshot (1000 entries)", timer.elapsed());
  std::printf("diff entries: %zu\n", diff.size());

  timer.start();
  store.generate(count);
  source.reset(); action.reset(); destination.reset();
  app.processEvents();
  report("full reset with new dataset", timer.elapsed());

  std::printf("rows per view: %d\n", static_cast<int>(store.visible.size()));
  std::printf("resident memory: %ld MB\n", rss_kb() / 1024);
  return 0;
}
