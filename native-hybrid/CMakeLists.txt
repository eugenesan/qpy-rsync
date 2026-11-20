cmake_minimum_required(VERSION 3.20)
project(qpy_rsync_hybrid LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT PYTHON_EXECUTABLE)
  set(PYTHON_EXECUTABLE /usr/bin/python3)
endif()

find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets)

execute_process(
  COMMAND "${PYTHON_EXECUTABLE}" -m nanobind --cmake_dir
  OUTPUT_VARIABLE NB_DIR
  OUTPUT_STRIP_TRAILING_WHITESPACE
  RESULT_VARIABLE NB_RESULT
)
if(NOT NB_RESULT EQUAL 0)
  message(FATAL_ERROR "nanobind is required")
endif()
list(APPEND CMAKE_PREFIX_PATH "${NB_DIR}")
find_package(Python COMPONENTS Interpreter Development REQUIRED)
find_package(nanobind CONFIG REQUIRED)

nanobind_add_module(native_hybrid hybrid.cpp)
target_link_libraries(native_hybrid PRIVATE Qt6::Core Qt6::Gui Qt6::Widgets)
