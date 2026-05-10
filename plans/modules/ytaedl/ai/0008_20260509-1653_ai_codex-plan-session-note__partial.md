---
plan_index: 0008
origin: ai
status: partial
source_file: 5_9_2025_16_53_plan.md
---

I feel like maybe we should use ffmpeg to determine filesize/url duration/etc when it's in question? Is this potentially better with less issues then what we use now? Is it even an option? Just saw the following log and had the above thoughts:
```
ffmpeg -analyzeduration 200M -probesize 1G -fflags +genpts  -i file:"B:\stars\sofi_li\Sofi Li & Akira Drago Horny Threesome ⧸ Embed Player.mp4" -map_metadata -1 -map_chapters -1 -threads 0 -map 0:0 -map 0:1 -map -0:s -codec:v:0 copy -bsf:v h264_mp4toannexb -start_at_zero -codec:a:0 copy -copyts -avoid_negative_ts disabled -max_muxing_queue_size 2048 -f hls -max_delay 5000000 -hls_time 6 -hls_segment_type mpegts -start_number 0 -hls_segment_filename "C:\ProgramData\Jellyfin\Server\cache\transcodes\88252b35c17f9a3843aa4f228f4b9e09%d.ts" -hls_playlist_type vod -hls_list_size 0 -y "C:\ProgramData\Jellyfin\Server\cache\transcodes\88252b35c17f9a3843aa4f228f4b9e09.m3u8"


ffmpeg version 7.1.3-Jellyfin Copyright (c) 2000-2025 the FFmpeg developers
  built with clang version 22.1.2 (https://github.com/msys2/MINGW-packages 4f19d31560faf73257116b7c95f0b322ba83d720)
  configuration: --cc=clang --pkg-config-flags=--static --extra-cflags=-I/clang64/ffbuild/include --extra-ldflags=-L/clang64/ffbuild/lib --prefix=/clang64/ffbuild/jellyfin-ffmpeg --extra-version=Jellyfin --disable-ffplay --disable-debug --disable-doc --disable-sdl2 --enable-lto=thin --enable-gpl --enable-version3 --enable-schannel --enable-iconv --enable-libxml2 --enable-zlib --enable-lzma --enable-gmp --enable-chromaprint --enable-libfreetype --enable-libfribidi --enable-libfontconfig --enable-libharfbuzz --enable-libass --enable-libbluray --enable-libmp3lame --enable-libopus --enable-libtheora --enable-libvorbis --enable-libopenmpt --enable-libwebp --enable-libvpx --enable-libzimg --enable-libx264 --enable-libx265 --enable-libsvtav1 --enable-libdav1d --enable-libfdk-aac --enable-opencl --enable-dxva2 --enable-d3d11va --enable-d3d12va --enable-amf --enable-libvpl --enable-ffnvcodec --enable-cuda --enable-cuda-llvm --enable-cuvid --enable-nvdec --enable-nvenc
  libavutil      59. 39.100 / 59. 39.100
  libavcodec     61. 19.101 / 61. 19.101
  libavformat    61.  7.100 / 61.  7.100
  libavdevice    61.  3.100 / 61.  3.100
  libavfilter    10.  4.100 / 10.  4.100
  libswscale      8.  3.100 /  8.  3.100
  libswresample   5.  3.100 /  5.  3.100
  libpostproc    58.  3.100 / 58.  3.100
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'file:B:\stars\sofi_li\Sofi Li & Akira Drago Horny Threesome Γº╕ Embed Player.mp4':
  Metadata:
    major_brand     : isom
    minor_version   : 512
    compatible_brands: isomiso2avc1mp41
    encoder         : Lavf58.29.100
  Duration: 00:26:15.05, start: 0.000000, bitrate: 729 kb/s
  Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p(progressive), 854x480 [SAR 1280:1281 DAR 16:9], 595 kb/s, 25 fps, 25 tbr, 12800 tbn (default)
      Metadata:
        handler_name    : VideoHandler
        vendor_id       : [0][0][0][0]
  Stream #0:1[0x2](eng): Audio: aac (LC) (mp4a / 0x6134706D), 44100 Hz, stereo, fltp, 128 kb/s (default)
      Metadata:
        handler_name    : SoundHandler
        vendor_id       : [0][0][0][0]
Stream mapping:
  Stream #0:0 -> #0:0 (copy)
  Stream #0:1 -> #0:1 (copy)
Output #0, hls, to 'C:\ProgramData\Jellyfin\Server\cache\transcodes\88252b35c17f9a3843aa4f228f4b9e09.m3u8':
  Metadata:
    encoder         : Lavf61.7.100
  Stream #0:0: Video: h264 (High) (avc1 / 0x31637661), yuv420p(progressive), 854x480 [SAR 1280:1281 DAR 16:9], q=2-31, 595 kb/s, 25 fps, 25 tbr, 90k tbn (default)
  Stream #0:1: Audio: aac (LC) (mp4a / 0x6134706D), 44100 Hz, stereo, fltp, 128 kb/s (default)

```

Also, if resolution is specified via -v, something like 2k for example. That would be the maximum allowable resolution downloadable. If 2k isn't available, the very next resolution available below 2k should be choosen - Just want to be sure that ordering is set in stone.
