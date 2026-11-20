// Phase 2b bridge: build native Qt views in a process that already runs a
// PySide6 QApplication, and hand the QWidget pointer back to Python.

#include <nanobind/nanobind.h>
#include <nanobind/stl/pair.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <QHBoxLayout>
#include <QHeaderView>
#include <QString>
#include <QTableView>
#include <QTreeView>
#include <QWidget>

#include <cstdint>
#include <string>
#include <utility>
#include <vector>

#include "model.hpp"

namespace nb = nanobind;

namespace {
DataStore g_store;
QWidget* g_widget = nullptr;
TableModel* g_source = nullptr;
TableModel* g_action = nullptr;
TableModel* g_destination = nullptr;
OverviewModel* g_overview = nullptr;
}  // namespace

NB_MODULE(native_qt_bridge, m) {
  m.def("generate", [](int count) { g_store.generate(count); });

  m.def("load_binary", [](const std::string& file) {
    qint64 read_ms = 0, parse_ms = 0;
    return g_store.load_binary(file, &read_ms, &parse_ms);
  });

  m.def("row_count", []() { return static_cast<int>(g_store.visible.size()); });

  m.def("create_widget", []() {
    if (g_widget == nullptr) {
      g_widget = new QWidget();
      auto* layout = new QHBoxLayout(g_widget);
      QTableView* views[3];
      for (int i = 0; i < 3; ++i) {
        views[i] = new QTableView(g_widget);
        views[i]->verticalHeader()->setDefaultSectionSize(22);
        views[i]->verticalHeader()->hide();
        views[i]->horizontalHeader()->setStretchLastSection(true);
        layout->addWidget(views[i]);
      }
      auto* overview_view = new QTreeView(g_widget);
      overview_view->setUniformRowHeights(true);
      overview_view->header()->setStretchLastSection(true);
      layout->addWidget(overview_view);

      g_source = new TableModel(&g_store, 0, g_widget);
      g_action = new TableModel(&g_store, 1, g_widget);
      g_destination = new TableModel(&g_store, 2, g_widget);
      g_overview = new OverviewModel(g_widget);
      views[0]->setModel(g_source);
      views[1]->setModel(g_action);
      views[2]->setModel(g_destination);
      overview_view->setModel(g_overview);
      overview_view->expandToDepth(0);
      g_widget->resize(1600, 800);
    }
    return reinterpret_cast<std::uintptr_t>(g_widget);
  });

  m.def("reset_views", []() {
    if (g_source == nullptr) return;
    g_source->reset();
    g_action->reset();
    g_destination->reset();
    g_overview->build(g_store);
  });

  m.def("toggle_decision", [](int path_id) { g_store.toggle_decision(path_id); });

  // The compact result Python pulls at validation/sync time.
  m.def("decision_diff", []() { return g_store.decision_log; });
}
