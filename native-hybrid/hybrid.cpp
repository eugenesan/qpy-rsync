// Production bridge for the hybrid app: Python owns rsync/parsing/validation,
// native Qt owns the four view models and the volatile decision table.

#include <nanobind/nanobind.h>
#include <nanobind/stl/pair.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <QHBoxLayout>
#include <QHeaderView>
#include <QItemSelectionModel>
#include <QTableView>
#include <QTreeView>
#include <QWidget>

#include <cstdint>
#include <string>
#include <vector>

#include "model.hpp"

namespace nb = nanobind;

namespace {
struct Session {
  DataStore store;
  QWidget* widget = nullptr;
  TableModel* models[3] = {nullptr, nullptr, nullptr};
  OverviewModel* overview = nullptr;
  QTableView* views[3] = {nullptr, nullptr, nullptr};
};

Session& session() {
  static Session value;
  return value;
}

using SelectionHook = void (*)(int path_id);
inline SelectionHook g_selection_hook = nullptr;

inline bool g_in_select = false;

void emit_selection(int path_id) {
  if (!g_in_select && g_selection_hook != nullptr) g_selection_hook(path_id);
}

nb::object g_selection_callback;

void selection_hook(int path_id) {
  if (!g_selection_callback.is_valid()) return;
  nb::gil_scoped_acquire gil;
  try {
    g_selection_callback(path_id);
  } catch (...) {
  }
}

nb::object g_decision_callback;

void decision_hook(int path_id, int decision) {
  if (!g_decision_callback.is_valid()) return;
  nb::gil_scoped_acquire gil;
  try {
    g_decision_callback(path_id, decision);
  } catch (...) {
    // Never let a Python exception escape a Qt signal handler.
  }
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

  m.def("set_selection_callback", [](nb::object callback) {
    g_selection_callback = callback;
    g_selection_hook = &selection_hook;
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

  m.def("set_decision_callback", [](nb::object callback) {
    g_decision_callback = callback;
    g_decision_hook = &decision_hook;
  });

  m.def("shutdown", []() {
    g_decision_hook = nullptr;
    g_selection_hook = nullptr;
    g_decision_callback = nb::object();
    g_selection_callback = nb::object();
  });

  m.def("row_count", []() {
    return static_cast<int>(session().store.visible.size());
  });

  m.def("create_widget", []() {
    Session& s = session();
    if (s.widget == nullptr) {
      s.widget = new QWidget();
      auto* layout = new QHBoxLayout(s.widget);
      QTableView* views[3];
      for (int i = 0; i < 3; ++i) {
        views[i] = new QTableView(s.widget);
        views[i]->verticalHeader()->setDefaultSectionSize(22);
        views[i]->verticalHeader()->hide();
        views[i]->horizontalHeader()->setStretchLastSection(true);
        layout->addWidget(views[i]);
      }
      auto* overview_view = new QTreeView(s.widget);
      overview_view->setUniformRowHeights(true);
      overview_view->header()->setStretchLastSection(true);
      layout->addWidget(overview_view);

      for (int i = 0; i < 3; ++i) s.views[i] = views[i];
      s.models[0] = new TableModel(&s.store, 0, s.widget);
      s.models[1] = new TableModel(&s.store, 1, s.widget);
      s.models[2] = new TableModel(&s.store, 2, s.widget);
      s.overview = new OverviewModel(s.widget);
      views[0]->setModel(s.models[0]);
      views[1]->setModel(s.models[1]);
      views[2]->setModel(s.models[2]);
      overview_view->setModel(s.overview);
      overview_view->expandToDepth(0);
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
      s.widget->resize(1600, 800);
    }
    return reinterpret_cast<std::uintptr_t>(s.widget);
  });

  m.def("set_action_filter", [](int mask) {
    session().store.action_mask = mask;
  });
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
    for (TableModel* model : s.models) model->reset();
  });
  m.def("search_text", [](const std::string& text) {
    return session().store.search(text);
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

  m.def("refresh", []() {
    Session& s = session();
    s.store.rebuild_visible();
    if (s.widget == nullptr) return;
    s.overview->build(s.store);
    for (TableModel* model : s.models) model->reset();
  });

  m.def("set_checkstate", [](int row, int checked) {
    Session& s = session();
    if (s.models[1] == nullptr) return;
    QModelIndex index = s.models[1]->index(row, 1);
    s.models[1]->setData(
        index, checked ? Qt::Checked : Qt::Unchecked, Qt::CheckStateRole);
  });

  m.def("toggle_decision", [](int path_id) {
    session().store.toggle_decision(path_id);
  });

  // Compact decision changes for Python's plan/validation path.
  m.def("decision_diff", []() { return session().store.decision_log; });
}
