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
#include <cstring>
#include <fstream>
#include <cstdlib>
#include <numeric>
#include <random>
#include <string>
#include <utility>
#include <vector>

namespace {

#include "model.hpp"

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
  std::string load_file;
  for (int i = 1; i < argc; ++i) {
    std::string arg = argv[i];
    if (arg.rfind("--items=", 0) == 0) count = std::atoi(arg.c_str() + 8);
    if (arg.rfind("--load=", 0) == 0) load_file = arg.substr(7);
  }

  QApplication app(argc, argv);
  QElapsedTimer timer;

  DataStore store;
  if (!load_file.empty()) {
    qint64 read_ms = 0, parse_ms = 0;
    timer.start();
    bool ok = store.load_binary(load_file, &read_ms, &parse_ms);
    if (!ok) {
      std::fprintf(stderr, "failed to load %s\n", load_file.c_str());
      return 2;
    }
    report("binary handoff total", timer.elapsed());
    report("binary handoff read (I/O)", read_ms);
    report("binary handoff parse/copy", parse_ms);
    count = static_cast<int>(store.paths.size());
  } else {
    timer.start();
    store.generate(count);
    report("store.generate", timer.elapsed());
  }

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
  report("first paint (4 panes, processEvents)", timer.elapsed());

  timer.start();
  for (int i = 0; i < 10; ++i) {
    QModelIndex far = views[0].model()->index(100000 + i * 10000, 0);
    views[0].scrollTo(far);
    app.processEvents();
  }
  report("10 x scroll 100k+ rows + paint", timer.elapsed());

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
