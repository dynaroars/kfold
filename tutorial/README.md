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

```
git submodule update --init --depth 1
```
or if you are outside of `git@github.com:dynaroars/linux-build`
```bash
git clone https://github.com/torvalds/linux --depth=1
```

4. Configure build options

Open up the interactive ncurse menu to select the build options.

```bash
cd linux
make menuconfig
```

5. Build the kernel

```bash
make -j24
```

... which may take about 2 mins for my PC.

Will see `Kernel: arch/x86/boot/bzImage is ready  (#1)` and it is the path to the kernel image.

6. Gather necessary things into `boot` directory

```bash
cd ..
mkdir boot
cp linux/arch/x86/boot/bzImage boot
```

# How to build user space

1. Clone BusyBox

```
git submodule update --init --depth 1
```
or if you are outside of `git@github.com:dynaroars/linux-build`
```bash
git clone https://git.busybox.net/busybox --depth=1
```

2. Configure build options

Open up the interative ncurse menu to select the build of options but this time for BusyBox, using the same command

```bash
cd busybox
make menuconfig
```

In BusyBox's menuconfig choose (Settings -> Build static binary (no shared libs)),
this option links the C library and everything else into the busybox executable.

Reason: A tiny system made of just a kernel and an initramfs has no /lib and no dynamic loader (ld-linux.so).
A dynamically linked busybox would fail at boot with "No such file or directory" (the missing interpreter), and the kernel would panic with "Attempted to kill init".

Also, choose (Settings -> Networking Utilities -> tc) and disable it to avoid network incompatibility.

3. Build the busybox

```bash
make -j24
```
... which just a blink of an eye.

4. Gather necessary things into `boot` directory

```bash
mkdir -p ../boot/initramfs
make CONFIG_PREFIX=../boot/initramfs install
```

`initramfs` is the initial file system the kernel loads after booting.
We will put busybox over there.
