cmake_minimum_required(VERSION 3.16)
project(driver_oscgoespurrr CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Output everything next to the source tree so the PyInstaller bundle can
# include it directly via `--add-data steamvr_toy_driver;steamvr_toy_driver`.
set(DRIVER_NAME driver_oscgoespurrr)
set(OUTDIR ${CMAKE_SOURCE_DIR}/bin/win64)
file(MAKE_DIRECTORY ${OUTDIR})

add_library(${DRIVER_NAME} SHARED
    src/driver.cpp
)

target_include_directories(${DRIVER_NAME} PRIVATE
    ${CMAKE_SOURCE_DIR}/include
)

# Static CRT — no VC++ Redistributable dependency on the end user's machine.
if (MSVC)
    set_property(TARGET ${DRIVER_NAME} PROPERTY MSVC_RUNTIME_LIBRARY "MultiThreaded")
    target_compile_definitions(${DRIVER_NAME} PRIVATE
        _CRT_SECURE_NO_WARNINGS
        WIN32_LEAN_AND_MEAN
        NOMINMAX
    )
    target_compile_options(${DRIVER_NAME} PRIVATE /W3 /EHsc)
endif()

set_target_properties(${DRIVER_NAME} PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY ${OUTDIR}
    LIBRARY_OUTPUT_DIRECTORY ${OUTDIR}
    ARCHIVE_OUTPUT_DIRECTORY ${OUTDIR}
    RUNTIME_OUTPUT_DIRECTORY_RELEASE ${OUTDIR}
    LIBRARY_OUTPUT_DIRECTORY_RELEASE ${OUTDIR}
    ARCHIVE_OUTPUT_DIRECTORY_RELEASE ${OUTDIR}
)
