# WordCraft and DeckCraft in the browser

Container `craft` in the stack (on by default, like Collabora): the browser versions of
[WordCraft](https://github.com/storytold/wordcraft) (documents, `.docx`) and
[DeckCraft](https://github.com/storytold/deckcraft) (presentations, `.pptx` / `.deckcraft`), served under
`/wordcraft/` and `/deckcraft/`. OfficeHub notices the container by itself: Word and PowerPoint files then open there
(HR can choose the office editor instead under **Administration → Office editing**).

Both apps are built from a fixed commit of OfficeHub's forks ([LetsManu/wordcraft](https://github.com/LetsManu/wordcraft),
[LetsManu/deckcraft](https://github.com/LetsManu/deckcraft), branch `officehub`; see `Dockerfile`):

- the app opens the file given in `?src=` and sends Save back to `?save=` (both same-site URLs with a short-lived
  ticket);
- DeckCraft edits together live: with `?collab=` it joins the file's session at OfficeHub
  (`/api/craft/collab/<file>`), sends its changes as Yjs updates and merges everyone else's. Undo takes back only your
  own steps; everyone sees who else is in the presentation and what they selected. `collab.json` in the image tells
  OfficeHub that this build can do it (older images keep one person at a time).

Nothing is sent outside the company.

To update: merge the upstream changes into the `officehub` branch of the forks, change the commits in the
`Dockerfile` and build the image.
