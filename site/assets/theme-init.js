// Runs in <head> before the page paints, so a saved light or dark choice never flashes.
// With nothing saved, use the dark Kolto Labs palette.
(function () {
  try {
    var saved = localStorage.getItem('modsync-site-theme');
    if (saved === 'light' || saved === 'dark') document.documentElement.dataset.theme = saved;
  } catch (e) {}
})();
