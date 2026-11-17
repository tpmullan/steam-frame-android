# Test pages and clips for Wolvic on the Frame

- `e360.html`: full-page click enters fullscreen on `e360.mp4`; open it as
  `http://HOST:PORT/e360.html?mozVideoProjection=360_auto` so Wolvic maps the clip as a 360 sphere
  (the parameter is read from the page URL when fullscreen starts; a bare video URL stays flat).
- `e360.mp4` is generated on the Frame (the guide has ffmpeg): eight 480 px vertical colour bands across a
  3840x1920 frame, red, yellow, green, cyan, blue, magenta, orange, grey. Straight ahead is the cyan|blue
  edge, so a heading change shows as a different pair of bands:

      ffmpeg -f lavfi -i "color=c=black:size=3840x1920:rate=24:duration=40,\
      drawbox=x=0:w=480:h=1920:c=red:t=fill,drawbox=x=480:w=480:h=1920:c=yellow:t=fill,\
      drawbox=x=960:w=480:h=1920:c=green:t=fill,drawbox=x=1440:w=480:h=1920:c=cyan:t=fill,\
      drawbox=x=1920:w=480:h=1920:c=blue:t=fill,drawbox=x=2400:w=480:h=1920:c=magenta:t=fill,\
      drawbox=x=2880:w=480:h=1920:c=orange:t=fill,drawbox=x=3360:w=480:h=1920:c=gray:t=fill" \
      -c:v libx264 -pix_fmt yuv420p -preset ultrafast e360.mp4
