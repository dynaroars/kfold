
# Setup

```bash
# libraries
pip3 install -r requirements.txt
# baseline
git submodule update --init code/baseline/kmax
pip install code/baseline/kmax
# cross compilers of the arm targets (linux-arm64, barebox: aarch64; linux-arm: arm)
sudo pacman -S aarch64-linux-gnu-gcc arm-none-eabi-gcc arm-none-eabi-binutils
sudo pacman -S arm-none-eabi-gcc arm-none-eabi-binutils
```

# Idea

> Hai: "should formulate as milp using scip/gurobi to solve faster than z3"
