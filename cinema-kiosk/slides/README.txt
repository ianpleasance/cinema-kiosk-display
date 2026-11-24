The updater puts the rendered slides here (this folder is not kept in git):

  current/            the slides on screen now (a link to the newest gen-... folder)
  gen-<date>-<time>/  the newest set and the one before it
  archive/<date>/     images of films that have left the schedule
  .tmp-.../           a set being built (appears briefly during an update)

Changes made inside current/ (deleting a slide you don't want, say) last only until
the next refresh. Put images you want to keep in ../static instead.
