cmake_minimum_required(VERSION 3.20)
project(qpy_rsync_native LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(QPY_NATIVE_WERROR "Treat native compiler warnings as errors" OFF)

if(NOT PYTHON_EXECUTABLE)
  set(PYTHON_EXECUTABLE /usr/bin/python3)
endif()

execute_process(
  COMMAND "${PYTHON_EXECUTABLE}" -m nanobind --cmake_dir
  OUTPUT_VARIABLE NB_DIR
  OUTPUT_STRIP_TRAILING_WHITESPACE
  RESULT_VARIABLE NB_RESULT
)
if(NOT NB_RESULT EQUAL 0)
  message(FATAL_ERROR "nanobind is required: ${PYTHON_EXECUTABLE} -m pip install nanobind")
endif()
list(APPEND CMAKE_PREFIX_PATH "${NB_DIR}")
find_package(Python COMPONENTS Interpreter Development REQUIRED)
find_package(nanobind CONFIG REQUIRED)

nanobind_add_module(_qpy_native native_module.cpp)

if(QPY_NATIVE_WERROR)
  if(MSVC)
    target_compile_options(_qpy_native PRIVATE /W4 /WX)
  else()
    target_compile_options(_qpy_native PRIVATE -Wall -Wextra -Werror)
  endif()
endif()

# Optional install target for a distribution that chooses to ship the module.
execute_process(
  COMMAND "${PYTHON_EXECUTABLE}" -c
          "import sysconfig; print(sysconfig.get_paths()['purelib'])"
  OUTPUT_VARIABLE PYTHON_SITE_PACKAGES
  OUTPUT_STRIP_TRAILING_WHITESPACE
)
install(TARGETS _qpy_native LIBRARY DESTINATION "${PYTHON_SITE_PACKAGES}")
