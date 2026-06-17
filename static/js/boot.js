/* ── Boot — called after all other scripts have loaded ─────────── */
/* This replaces the inline <script> block in index.html to comply
   with the Content Security Policy (script-src 'self'). */
initApp();
initSettings();
