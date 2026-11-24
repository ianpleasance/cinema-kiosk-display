If VIDEO_MODE in .env is plain, fade or both, the updater saves the slideshow video here:

  slideshow.mp4        slides held for HOLD_SECONDS, no fades
  slideshow-fade.mp4   with the FADE_SECONDS / FADE_MODE fades

Videos are only remade when the slides or the related settings change. Switch VIDEO_MODE
and the video you no longer ask for is deleted. This folder is not kept in git.
