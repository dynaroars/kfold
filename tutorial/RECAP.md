# Linux kernel

The Linux kernel is the core program of a Linux operating system. It runs first when the machine boots, and it has full control of the hardware.

## What it does

- Process management: it decides which program runs on which CPU core and for how long (scheduling).
- Memory management: it gives each process its own virtual address space, handles paging and swapping, and keeps processes from reading each other's memory.
- Device drivers: it talks to disks, GPUs, network cards, USB devices and so on. Most of the kernel's source code is drivers.
- File systems: it provides ext4, btrfs, XFS and others behind one common interface (VFS).
- Networking: it implements the TCP/IP stack, firewalling (netfilter) and sockets.
- System calls: it gives user programs a controlled way to ask for kernel services, such as open, read, fork and mmap.
- Security and isolation: it enforces permissions, namespaces, cgroups (the basis of containers) and mandatory access control such as SELinux.

It runs on everything from phones (Android) and routers to servers and supercomputers.

## What it is not

Linux is only the kernel.
A full distribution (Arch, Debian, Fedora) adds the C library, a shell, system tools, init/systemd, a package manager and a desktop.
This is why people say "GNU/Linux".

---

# User space

User space is where ordinary programs run, separate from the kernel.
The kernel runs in kernel space, with full hardware access.
Everything else (your shell, browser, editor, systemd, the C library) runs in user space with restricted privileges.

---

# BusyBox

BusyBox is a single small executable that provides stripped-down versions of many standard Unix command-line tools.
It is often called "the Swiss Army knife of embedded Linux.

## How it works
- One binary, busybox, contains implementations of ls, cp, cat, grep, sed, mount, ps, ifconfig, vi and several hundred more, plus a small shell (ash) and a minimal init.
- The tools are installed as symlinks (or hard links) to that binary: /bin/ls -> busybox, /bin/cp -> busybox, and so on.
- When it starts, BusyBox checks the name it was invoked as (argv[0]) and runs the matching applet. You can also call it directly: busybox ls -l.

---

# Bootloader

A bootloader is the small program that runs right after the firmware starts the machine.
Its job is to load the operating system kernel into memory and hand control to it.

## Syslinux vs GRUB

Syslinux is small and simple, while GRUB is large and flexible.
Pick Syslinux when you want a minimal, easy-to-configure loader (especially for ISOs, USB sticks and network boot).
Pick GRUB when you need broad support and scripting.
