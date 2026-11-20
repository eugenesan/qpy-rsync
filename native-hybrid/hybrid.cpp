// Production bridge for the hybrid app: Python owns rsync/parsing/validation,
// native Qt owns the view models and the volatile decision table.

#include <nanobind/nanobind.h>
#include <nanobind/stl/pair.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <QColor>
#include <QCursor>
#include <QHBoxLayout>
#include <QMenu>
#include <QPainter>
#include <QHeaderView>
#include <QItemSelectionModel>
#include <QLabel>
#include <QScrollBar>
#include <QSizePolicy>
#include <QStyledItemDelegate>
#include <QSplitter>
#include <QTableView>
#include <QStyleOptionViewItem>
#include <QTreeView>
#include <QVBoxLayout>
#include <QWidget>

#include <cstdint>
#include <string>
#include <vector>

#include "model.hpp"

namespace nb = nanobind;

namespace {
struct Session {
  DataStore store;
  QWidget* widget = nullptr;  // legacy combined widget
  QWidget* tables_widget = nullptr;
  QWidget* overview_widget = nullptr;
  QTreeView* overview_view = nullptr;
  QLabel* stats_label = nullptr;
  std::vector<QString> action_colours;
  TableModel* models[3] = {nullptr, nullptr, nullptr};
  OverviewModel* overview = nullptr;
  QTableView* views[3] = {nullptr, nullptr, nullptr};
};

Session& session() {
  static Session value;
  return value;
}

using SelectionHook = void (*)(int path_id);
using DecisionHook = void (*)(int path_id, int decision);
using ContextHook = void (*)(int pane, const char* path, int x, int y);

inline SelectionHook g_selection_hook = nullptr;
inline DecisionHook g_native_decision_hook = nullptr;
inline bool g_in_select = false;
inline nb::object g_selection_callback;
inline nb::object g_decision_callback;
inline nb::object g_context_callback;

void emit_selection(int path_id) {
  if (!g_in_select && g_selection_hook != nullptr) g_selection_hook(path_id);
}

void selection_hook(int path_id) {
  if (!g_selection_callback.is_valid()) return;
  nb::gil_scoped_acquire gil;
  try {
    g_selection_callback(path_id);
  } catch (...) {
  }
}

void native_decision_hook(int path_id, int decision) {
  if (!g_decision_callback.is_valid()) return;
  nb::gil_scoped_acquire gil;
  try {
    g_decision_callback(path_id, decision);
  } catch (...) {
  }
}

void context_hook(int pane, const char* path, int x, int y) {
  if (!g_context_callback.is_valid()) return;
  nb::gil_scoped_acquire gil;
  try {
    g_context_callback(pane, nb::str(path), x, y);
  } catch (...) {
  }
}

void refresh_native_models(Session& s) {
  int positions[3] = {0, 0, 0};
  for (int i = 0; i < 3; ++i) {
    if (s.views[i] != nullptr && s.views[i]->verticalScrollBar() != nullptr) {
      positions[i] = s.views[i]->verticalScrollBar()->value();
    }
  }
  for (TableModel* model : s.models) model->reset();
  for (int i = 0; i < 3; ++i) {
    if (s.views[i] != nullptr && s.views[i]->verticalScrollBar() != nullptr) {
      s.views[i]->verticalScrollBar()->setValue(positions[i]);
    }
  }
}

class HybridDelegate : public QStyledItemDelegate {
 public:
  HybridDelegate(Session* session, int pane, QObject* parent = nullptr)
      : QStyledItemDelegate(parent), session_(session), pane_(pane) {}

  void paint(QPainter* painter, const QStyleOptionViewItem& option,
             const QModelIndex& index) const override {
    QStyleOptionViewItem opt(option);
    initStyleOption(&opt, index);
    Session& s = *session_;
    const int row = index.row();
    const DataStore& store = s.store;
    if (row >= 0 && row < static_cast<int>(store.visible.size())) {
      const int id = store.visible[row];
      if (row % 2 == 0) opt.features |= QStyleOptionViewItem::Alternate;
      if (pane_ != 1 && id >= 0 && id < static_cast<int>(store.actions.size()) &&
          id < static_cast<int>(s.action_colours.size())) {
        const QString& colour = s.action_colours[store.actions[id]];
        if (!colour.isEmpty()) opt.palette.setColor(QPalette::Text, QColor(colour));
      }
      if (id < static_cast<int>(store.decisions.size()) && store.decisions[id] == Exclude) {
        opt.palette.setColor(QPalette::Text, Qt::gray);
      }
      if (index.column() == 0 && id < static_cast<int>(store.depth.size())) {
        const int indent = store.depth[id] * 14;
        opt.rect.adjust(indent, 0, 0, 0);
      }
      QStyledItemDelegate::paint(painter, opt, index);
      if (index.column() == 0 && id < static_cast<int>(store.is_dir.size()) &&
          store.is_dir[id]) {
        painter->save();
        painter->setBrush(QColor("#0891B2"));
        painter->setPen(Qt::NoPen);
        QRect r = opt.rect;
        int x = r.left() - 11;
        int y = r.center().y();
        QPoint points[3] = {{x, y - 4}, {x + 7, y}, {x, y + 4}};
        painter->drawPolygon(points, 3);
        painter->restore();
      }
      return;
    }
    QStyledItemDelegate::paint(painter, opt, index);
  }

 private:
  Session* session_;
  int pane_;
};

QWidget* ensure_tables_widget(Session& s) {
  if (s.tables_widget == nullptr) {
    s.tables_widget = new QWidget();
    auto* outer = new QVBoxLayout(s.tables_widget);
    outer->setContentsMargins(0, 0, 0, 0);
    auto* splitter = new QSplitter(Qt::Horizontal, s.tables_widget);
    splitter->setChildrenCollapsible(false);
    outer->addWidget(splitter);
    QTableView* views[3];
    for (int i = 0; i < 3; ++i) {
      views[i] = new QTableView(s.tables_widget);
      views[i]->verticalHeader()->setDefaultSectionSize(22);
      views[i]->verticalHeader()->hide();
      views[i]->horizontalHeader()->setStretchLastSection(true);
      views[i]->setVerticalScrollBarPolicy(Qt::ScrollBarAlwaysOn);
      splitter->addWidget(views[i]);
    }
    for (int i = 0; i < 3; ++i) s.views[i] = views[i];
    s.models[0] = new TableModel(&s.store, 0, s.tables_widget);
    s.models[1] = new TableModel(&s.store, 1, s.tables_widget);
    s.models[2] = new TableModel(&s.store, 2, s.tables_widget);
    views[0]->setModel(s.models[0]);
    views[1]->setModel(s.models[1]);
    views[2]->setModel(s.models[2]);
    for (int i = 0; i < 3; ++i) {
      views[i]->setItemDelegate(new HybridDelegate(&s, i, s.tables_widget));
      views[i]->setContextMenuPolicy(Qt::CustomContextMenu);
      QObject::connect(
          views[i], &QTableView::customContextMenuRequested,
          [i](const QPoint& pos) {
            Session& current = session();
            if (current.views[i] == nullptr) return;
            QModelIndex index = current.views[i]->indexAt(pos);
            if (!index.isValid()) return;
            int row = index.row();
            if (row < 0 || row >= static_cast<int>(current.store.visible.size())) return;
            int id = current.store.visible[row];
            std::string path = current.store.paths[id];
            QPoint global = current.views[i]->viewport()->mapToGlobal(pos);
            context_hook(i, path.c_str(), global.x(), global.y());
          });
    }
    for (int i = 0; i < 3; ++i) {
      for (int j = i + 1; j < 3; ++j) {
        QObject::connect(views[i]->verticalScrollBar(), &QScrollBar::valueChanged,
                         views[j]->verticalScrollBar(), &QScrollBar::setValue);
        QObject::connect(views[j]->verticalScrollBar(), &QScrollBar::valueChanged,
                         views[i]->verticalScrollBar(), &QScrollBar::setValue);
      }
    }
    for (QTableView* view : views) {
      QObject::connect(
          view->selectionModel(), &QItemSelectionModel::selectionChanged,
          [](const QItemSelection& selected, const QItemSelection&) {
            if (selected.isEmpty()) return;
            QModelIndex index = selected.first().indexes().first();
            Session& current = session();
            int row = index.row();
            if (row >= 0 && row < static_cast<int>(current.store.visible.size())) {
              emit_selection(current.store.visible[row]);
            }
          });
    }
    splitter->setStretchFactor(0, 1);
    splitter->setStretchFactor(1, 0);
    splitter->setStretchFactor(2, 1);
    QSizePolicy policy = views[1]->sizePolicy();
    policy.setHorizontalPolicy(QSizePolicy::Fixed);
    views[1]->setSizePolicy(policy);
    views[1]->setFixedWidth(180);
    s.tables_widget->setMinimumWidth(700);
  }
  return s.tables_widget;
}

QWidget* ensure_overview_widget(Session& s) {
  if (s.overview_widget == nullptr) {
    s.overview_widget = new QWidget();
    auto* layout = new QVBoxLayout(s.overview_widget);
    layout->setContentsMargins(0, 0, 0, 0);
    s.stats_label = new QLabel(s.overview_widget);
    s.stats_label->setWordWrap(true);
    layout->addWidget(s.stats_label);
    s.overview_view = new QTreeView(s.overview_widget);
    s.overview_view->setUniformRowHeights(true);
    s.overview_view->setAlternatingRowColors(true);
    s.overview_view->setRootIsDecorated(true);
    s.overview_view->header()->setStretchLastSection(true);
    s.overview = new OverviewModel(s.overview_widget);
    s.overview_view->setModel(s.overview);
    s.overview_view->expandToDepth(2);
    layout->addWidget(s.overview_view);
  }
  return s.overview_widget;
}

void update_stats(Session& s) {
  if (s.stats_label == nullptr) return;
  long long count = 0, size = 0;
  for (int id : s.store.visible) {
    if (id >= 0 && id < static_cast<int>(s.store.sizes.size())) {
      ++count;
      size += s.store.sizes[id];
    }
  }
  s.stats_label->setText(QString("%1 item(s), %2 B").arg(count).arg(size));
}


}  // namespace

NB_MODULE(native_hybrid, m) {
  m.doc() = "Native Qt view layer for qpy-rsync";

  m.def("load", [](const std::vector<std::string>& paths,
                   const std::vector<int>& actions,
                   const std::vector<int>& kinds,
                   const std::vector<long long>& sizes,
                   const std::vector<int>& decisions,
                   const std::vector<std::string>& times) {
    session().store.load_direct(paths, actions, kinds, sizes, decisions, times);
  });

  m.def("truncate", [](int count) {
    Session& s = session();
    s.store.truncate(count);
  });

  m.def("append", [](const std::vector<std::string>& paths,
                     const std::vector<int>& actions,
                     const std::vector<int>& kinds,
                     const std::vector<long long>& sizes,
                     const std::vector<int>& decisions,
                     const std::vector<std::string>& times) {
    session().store.append_direct(paths, actions, kinds, sizes, decisions, times);
  });

  m.def("set_selection_callback", [](nb::object callback) {
    g_selection_callback = callback;
    g_selection_hook = &selection_hook;
  });

  m.def("set_decision_callback", [](nb::object callback) {
    g_decision_callback = callback;
    g_native_decision_hook = &native_decision_hook;
    g_decision_hook = &native_decision_hook;
  });

  m.def("shutdown", []() {
    g_selection_hook = nullptr;
    g_native_decision_hook = nullptr;
    g_decision_hook = nullptr;
    g_selection_callback = nb::object();
    g_decision_callback = nb::object();
    g_context_callback = nb::object();
  });

  m.def("debug_row_of_id", [](int path_id) {
    Session& s = session();
    return path_id >= 0 && path_id < static_cast<int>(s.store.row_of_id.size())
               ? s.store.row_of_id[path_id] : -2;
  });

  m.def("debug_selected_row", []() {
    Session& s = session();
    if (s.views[0] == nullptr || s.views[0]->selectionModel() == nullptr) return -2;
    QModelIndexList rows = s.views[0]->selectionModel()->selectedRows();
    return rows.isEmpty() ? -1 : rows.first().row();
  });

  m.def("select_path_id", [](int path_id) {
    Session& s = session();
    if (path_id < 0 || path_id >= static_cast<int>(s.store.row_of_id.size())) return;
    int row = s.store.row_of_id[path_id];
    g_in_select = true;
    for (QTableView* view : s.views) {
      if (view == nullptr || view->model() == nullptr) continue;
      QModelIndex index = view->model()->index(row, 0);
      if (!index.isValid()) continue;
      view->selectionModel()->select(
          index, QItemSelectionModel::ClearAndSelect | QItemSelectionModel::Rows);
      view->scrollTo(index);
    }
    g_in_select = false;
    emit_selection(path_id);
  });

  m.def("overview_folder_count", []() {
    Session& s = session();
    if (s.overview == nullptr) return 0;
    QModelIndex root = s.overview->index(0, 0);
    if (!root.isValid()) return 0;
    QModelIndex all = s.overview->index(0, 0, root);
    return all.isValid() ? s.overview->rowCount(all) : 0;
  });

  m.def("row_count", []() {
    return static_cast<int>(session().store.visible.size());
  });

  m.def("create_tables_widget", []() {
    return reinterpret_cast<std::uintptr_t>(ensure_tables_widget(session()));
  });

  m.def("create_overview_widget", []() {
    return reinterpret_cast<std::uintptr_t>(ensure_overview_widget(session()));
  });

  m.def("update_stats", []() { update_stats(session()); });

  m.def("create_widget", []() {
    Session& s = session();
    if (s.widget == nullptr) {
      QWidget* tables = ensure_tables_widget(s);
      QWidget* overview = ensure_overview_widget(s);
      s.widget = new QWidget();
      auto* layout = new QHBoxLayout(s.widget);
      layout->addWidget(tables);
      layout->addWidget(overview);
      s.widget->setMinimumSize(1000, 500);
      s.widget->resize(1600, 800);
    }
    return reinterpret_cast<std::uintptr_t>(s.widget);
  });

  m.def("set_context_callback", [](nb::object callback) {
    g_context_callback = callback;
  });

  m.def("set_action_colours", [](const std::vector<std::string>& colours) {
    Session& s = session();
    s.action_colours.clear();
    for (const std::string& value : colours) {
      s.action_colours.push_back(QString::fromStdString(value));
    }
    for (TableModel* model : s.models) model->layout_refresh();
  });

  m.def("set_action_filter", [](int mask) { session().store.action_mask = mask; });

  m.def("set_pattern", [](const std::string& pattern, bool glob,
                          bool dirs_only, bool include_contents) {
    Session& s = session();
    s.store.pattern = pattern;
    s.store.pattern_glob = glob;
    s.store.dirs_only = dirs_only;
    s.store.include_contents = include_contents;
  });

  m.def("set_collapsed", [](int path_id, bool value) {
    session().store.set_collapsed(path_id, value);
  });

  m.def("set_collapsed_by_path", [](const std::string& path, bool value) {
    Session& s = session();
    auto it = s.store.path_to_id.find(path);
    if (it != s.store.path_to_id.end()) s.store.set_collapsed(it->second, value);
  });

  m.def("set_sort", [](int column, bool descending) {
    Session& s = session();
    s.store.sort_column = column;
    s.store.sort_desc = descending;
  });

  m.def("refresh_visible", []() {
    Session& s = session();
    s.store.rebuild_visible();
    refresh_native_models(s);
    update_stats(s);
  });

  m.def("set_show_excluded", [](bool show) {
    Session& s = session();
    s.store.show_excluded = show;
    s.store.rebuild_visible();
    refresh_native_models(s);
    update_stats(s);
  });

  m.def("apply_python_decisions", [](const std::vector<std::pair<int, int>>& pairs) {
    Session& s = session();
    std::vector<int> target(s.store.decisions.size(), Inherit);
    for (const auto& pair : pairs) {
      if (pair.first >= 0 && pair.first < static_cast<int>(target.size())) {
        target[pair.first] = pair.second;
      }
    }
    int changed_id = -1;
    int changed_count = 0;
    for (std::size_t i = 0; i < target.size(); ++i) {
      if (target[i] == s.store.decisions[i]) continue;
      ++changed_count;
      changed_id = static_cast<int>(i);
      s.store.decisions[i] = target[i];
    }
    s.store.decision_log.clear();
    if (changed_count == 1 &&
        s.store.update_single_visibility(changed_id, target[changed_id])) {
      for (TableModel* model : s.models) model->layout_refresh();
      update_stats(s);
    } else if (changed_count > 0) {
      s.store.rebuild_visible();
      refresh_native_models(s);
      update_stats(s);
    }
  });

  m.def("refresh_after_decision", [](int path_id, int decision) {
    Session& s = session();
    if (decision != Exclude) return;
    s.store.rebuild_visible();
    refresh_native_models(s);
    update_stats(s);
  });

  m.def("refresh", []() {
    Session& s = session();
    s.store.rebuild_visible();
    if (s.tables_widget == nullptr) {
      // Standalone callers may not have created widgets yet.
      return;
    }
    if (s.overview != nullptr) s.overview->build(s.store);
    refresh_native_models(s);
    update_stats(s);
  });

  m.def("selected_path", []() {
    Session& s = session();
    if (s.views[0] == nullptr || s.views[0]->selectionModel() == nullptr) return std::string();
    QModelIndexList rows = s.views[0]->selectionModel()->selectedRows();
    if (rows.isEmpty()) return std::string();
    int row = rows.first().row();
    if (row < 0 || row >= static_cast<int>(s.store.visible.size())) return std::string();
    return s.store.paths[s.store.visible[row]];
  });

  m.def("path_of_row", [](int row) {
    Session& s = session();
    if (row < 0 || row >= static_cast<int>(s.store.visible.size())) return std::string();
    return s.store.paths[s.store.visible[row]];
  });

  m.def("search_text", [](const std::string& text) {
    Session& s = session();
    if (text.size() > 1 && text.back() == '/') {
      std::string name = text.substr(0, text.size() - 1);
      const bool by_path = name.find('/') != std::string::npos;
      std::vector<int> result;
      for (int row = 0; row < static_cast<int>(s.store.visible.size()); ++row) {
        int id = s.store.visible[row];
        if (id >= static_cast<int>(s.store.is_dir.size()) || !s.store.is_dir[id]) continue;
        const std::string& candidate = by_path ? s.store.folded_paths[id]
                                               : s.store.folded_names[id];
        if (candidate == name) result.push_back(row);
      }
      return result;
    }
    return s.store.search(text);
  });

  m.def("toggle_decision", [](int path_id) { session().store.toggle_decision(path_id); });

  m.def("set_checkstate", [](int row, int checked) {
    Session& s = session();
    if (s.models[1] == nullptr) return;
    QModelIndex index = s.models[1]->index(row, 1);
    s.models[1]->setData(
        index, checked ? Qt::Checked : Qt::Unchecked, Qt::CheckStateRole);
  });

  m.def("decision_diff", []() { return session().store.decision_log; });
}
