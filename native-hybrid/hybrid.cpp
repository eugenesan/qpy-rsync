// Production bridge for the hybrid app: Python owns rsync/parsing/validation,
// native Qt owns the four view models and the volatile decision table.

#include <nanobind/nanobind.h>
#include <nanobind/stl/pair.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <QHBoxLayout>
#include <QHeaderView>
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
};

Session& session() {
  static Session value;
  return value;
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
                   const std::vector<int>& decisions) {
    session().store.load_direct(paths, actions, kinds, sizes, decisions);
  });

  m.def("set_decision_callback", [](nb::object callback) {
    g_decision_callback = callback;
    g_decision_hook = &decision_hook;
  });

  m.def("shutdown", []() {
    g_decision_hook = nullptr;
    g_decision_callback = nb::object();
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

      s.models[0] = new TableModel(&s.store, 0, s.widget);
      s.models[1] = new TableModel(&s.store, 1, s.widget);
      s.models[2] = new TableModel(&s.store, 2, s.widget);
      s.overview = new OverviewModel(s.widget);
      views[0]->setModel(s.models[0]);
      views[1]->setModel(s.models[1]);
      views[2]->setModel(s.models[2]);
      overview_view->setModel(s.overview);
      overview_view->expandToDepth(0);
      s.widget->resize(1600, 800);
    }
    return reinterpret_cast<std::uintptr_t>(s.widget);
  });

  m.def("refresh", []() {
    Session& s = session();
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
