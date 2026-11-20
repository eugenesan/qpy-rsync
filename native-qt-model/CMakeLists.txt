cmake_minimum_required(VERSION 3.20)
project(native_qt_model LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets)

qt_add_executable(native_qt_model main.cpp)
target_link_libraries(native_qt_model PRIVATE Qt6::Core Qt6::Gui Qt6::Widgets)
