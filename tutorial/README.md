# How to build a linux kernel

1. Update

```bash
sudo pacman -Syu
```

2. Install dependency

```bash
sudo pacman -Sy bzip2 git vim make gcc ncurses flex bison bc openssl libelf cpio
```

- `bzip2`: required for BusyBox
- `git vim make gcc`: basic tools
- `ncurses`: for kconfig menu
- `flex bison bc openssl libelf`: for the kernel
- `cpio`: required for init RAM

3. Clone the linux kernel

```bash
git clone https://github.com/torvalds/linux --depth=1
```

4. Configure build options

Open up the interactive ncurse menu to select the build options.

```bash
cd linux
make menuconfig
```
