###############################################################################
# Set target specific compiler/linker flags

set(MCU_FAMILY STM32F0)

set(ARCH_CPU_FLAGS "-mcpu=cortex-m0")
set(ARCH_FPU_FLAGS "-mfloat-abi=soft")

set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} \
    ${ARCH_CPU_FLAGS} \
    ${ARCH_FPU_FLAGS} \
" CACHE INTERNAL "C Compiler options")

set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} \
    ${ARCH_CPU_FLAGS} \
    ${ARCH_FPU_FLAGS} \
" CACHE INTERNAL "C++ Compiler options")

set(CMAKE_ASM_FLAGS "${CMAKE_ASM_FLAGS} \
    ${ARCH_CPU_FLAGS} \
    ${ARCH_FPU_FLAGS} \
" CACHE INTERNAL "ASM Compiler options")

# Linker flags
set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} \
    -T${LINKER_SCRIPT} \
" CACHE INTERNAL "Linker options")
