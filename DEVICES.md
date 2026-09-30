# Which computers can run Nova

Nova runs on Windows, Mac and Linux computers from 2020 onward, and on many
older ones. Find your computer below to see which file to download from the
[Releases](../../releases) page.

**Not sure what you have?**
- **Windows:** Start > Settings > System > About. Look at "System type" and "Edition".
- **Mac:** Apple menu > About This Mac. "Chip" says Apple M1, M2… or "Processor" says Intel.
- **Linux:** run `uname -m` (x86_64 means Intel or AMD) and check your distribution's version.

## Windows

**Download:** the `.exe` (for example `N.O.V.A.Setup.0.1.0.exe`)

| | |
|---|---|
| Works on | Windows 10 or Windows 11, 64-bit |
| Processors | Intel or AMD (almost every Windows laptop and desktop) |
| Examples | Dell XPS / Inspiron / Latitude, HP Pavilion / Envy / Spectre, Lenovo ThinkPad / IdeaPad / Yoga, ASUS, Acer, MSI, Microsoft Surface Laptop and Surface Pro (Intel), custom-built PCs, from 2020 to today and most from before |
| Windows on ARM | Surface Pro X, Surface Pro 9/11 (5G/Snapdragon) and other Snapdragon laptops run Nova on Windows 11 through Windows' built-in emulation. Expect it to be slower. Not yet tested |
| Doesn't work on | Windows 7 or 8, 32-bit Windows, Windows 10 in S mode (switch out of S mode first) |

**First time you open it:** if a blue "Windows protected your PC" screen
appears, click **More info**, then **Run anyway**. You only do this once.

## Mac

Macs come in two kinds. Pick the file that matches yours.

### Mac with an Apple chip (M1, M2, M3, M4 and newer)

**Download:** the `.dmg` with `arm64` in its name (or the `-arm64-mac.zip`)

| | |
|---|---|
| Works on | macOS 13.5 Ventura or newer (every Mac with an Apple chip can update to it for free) |
| Examples | MacBook Air (M1, 2020) and every MacBook Air since, MacBook Pro 13" (M1, 2020) and every MacBook Pro since, Mac mini (M1, 2020) and later, iMac 24" (2021) and later, Mac Studio, Mac Pro (2023) |

### Mac with an Intel chip

**Download:** the `.dmg` **without** `arm64` in its name (or `N.O.V.A-…-mac.zip`: unzip it and drag Nova into Applications)

| | |
|---|---|
| Works on | macOS 13.5 Ventura or newer |
| 2020 models | MacBook Air (2020, Intel), MacBook Pro 13" and 16" (2019–2020, Intel), iMac 21.5" and 27" (2020), Mac Pro (2019), Mac mini (2018) |
| Older models | Intel Macs that can run macOS Ventura: MacBook Air (2018 and later), MacBook Pro (2017 and later), iMac (2017 and later), iMac Pro, Mac mini (2018 and later) |
| Doesn't work on | Macs that can't update past macOS 12 Monterey |

On an older macOS? Updating is free: Apple menu > System Settings (or System
Preferences) > Software Update. A Mac with an Apple chip can also run the Intel
version through Rosetta, but the `arm64` version is much faster.

**First time you open it:** if macOS says Nova can't be opened, choose
**Done**, then go to **System Settings > Privacy & Security**, scroll down and
click **Open Anyway**. You only do this once.

## Linux

**Download:** the `.AppImage` (any distribution) or the `.deb` (Ubuntu, Debian and their relatives)

| | |
|---|---|
| Works on | 64-bit Intel or AMD computers |
| Distributions | Ubuntu 20.04 or newer, Linux Mint 20 or newer, Pop!\_OS 20.04 or newer, Debian 11 or newer, Fedora 36 or newer, openSUSE Leap 15.3 or newer, Arch and other rolling releases, elementary OS 6 or newer, Zorin OS 16 or newer |
| Examples | Any laptop or desktop above, including Dell XPS Developer Edition, Lenovo ThinkPad, System76 and Framework laptops |
| Chromebooks | Intel or AMD Chromebooks with Linux turned on can install the `.deb`. Not yet tested |
| Doesn't work on | ARM computers (Raspberry Pi, ARM Chromebooks, Pinebook), 32-bit Linux |

**AppImage tip:** make it runnable first (`chmod +x N.O.V.A-*.AppImage`, or
right-click > Properties > Allow executing). Ubuntu 22.04 and newer also need
`libfuse2` for AppImages: `sudo apt install libfuse2` (on Ubuntu 24.04 it's
`libfuse2t64`).

## Phones and tablets

Nova doesn't install on phones or tablets. You use it from them instead: Nova
runs on your computer, and your phone opens it as an app. Set it up in
Settings > Remote.

| | |
|---|---|
| iPhone and iPad | Safari, then Share > Add to Home Screen. Notifications need iOS/iPadOS 16.4 or newer |
| Android phones and tablets | Chrome, then Install app |
| Needs | Nova open on your computer, and the phone on the same network (or connected with Tailscale from anywhere) |

## What your computer needs

| | Minimum | Better |
|---|---|---|
| Memory (RAM) | 8 GB | 16 GB or more, especially for free local models |
| Free space | 3 GB | 10 GB or more if you add local models (each is 2–10 GB) |
| Internet | Needed for online models, online voices and school sites | Local models work offline |
| Microphone | Only for talking to Nova | |

## How this is checked

Every release is built and started on Windows, on Macs with both kinds of
chip, and on Ubuntu. The build also checks that every file it bundles is made
for macOS 13.5 and for Linux systems as old as Ubuntu 20.04. If one isn't, the
release isn't published. The older systems above are supported by how Nova is
built, but haven't all been tested on real hardware. If Nova doesn't work on
your computer, please [open an issue](../../issues) with your model and system
version.
