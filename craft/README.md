# WordCraft and DeckCraft in the browser

Container `craft` in the stack (on by default, like Collabora): the browser versions of
[WordCraft](https://github.com/storytold/wordcraft) (documents, `.docx`) and
[DeckCraft](https://github.com/storytold/deckcraft) (presentations, `.pptx` / `.deckcraft`), served under
`/wordcraft/` and `/deckcraft/`. OfficeHub notices the container by itself: Word and PowerPoint files then open there
(HR can choose the office editor instead under **Administration → Office editing**).

Both apps are built from a fixed commit of their source (see `Dockerfile`) with a small patch (`patches/`): the app
opens the file given in `?src=` and sends Save back to `?save=` (both same-site URLs with a short-lived ticket);
everything else in the apps stays as it is. Nothing is sent outside the company.

To update: change the commits in the `Dockerfile`, check that the patches still apply, and build the image.
