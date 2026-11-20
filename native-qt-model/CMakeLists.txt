cmake_minimum_required(VERSION 3.20)
project(native_qt_model LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT PYTHON_EXECUTABLE)
  set(PYTHON_EXECUTABLE /usr/bin/python3)
endif()

find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets)

qt_add_executable(native_qt_model main.cpp)
target_link_libraries(native_qt_model PRIVATE Qt6::Core Qt6::Gui Qt6::Widgets)

# Nanobind bridge for the PySide6 embedding experiment.
execute_process(
  COMMAND "${PYTHON_EXECUTABLE}" -m nanobind --cmake_dir
  OUTPUT_VARIABLE NB_DIR
  OUTPUT_STRIP_TRAILING_WHITESPACE
  RESULT_VARIABLE NB_RESULT
)
if(NB_RESULT EQUAL 0)
  list(APPEND CMAKE_PREFIX_PATH "${NB_DIR}")
  find_package(Python COMPONENTS Interpreter Development REQUIRED)
  find_package(nanobind CONFIG REQUIRED)
  nanobind_add_module(native_qt_bridge bridge.cpp)
  target_link_libraries(native_qt_bridge PRIVATE Qt6::Core Qt6::Gui Qt6::Widgets)
endif()
