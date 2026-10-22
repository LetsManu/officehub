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
- both edit together live: with `?collab=` the app joins the file's session at OfficeHub (`/api/craft/collab/<file>`),
  sends its changes as Yjs updates and merges everyone else's – in WordCraft down to the character (two people can
  type in the same paragraph), in DeckCraft per shape and character. Undo takes back only your own steps; everyone
  sees who else is there (WordCraft: their caret with their name; DeckCraft: what they selected). In tables every
  cell is shared on its own, so people type in different cells or the same cell at once; a change to the table itself
  (a new row or column) is one piece (the last one wins), the cells keep their text. While a file is shared, each
  person's new comments, headers and pictures get ids from a range of their own, so they never clash. `collab.json` in the image tells OfficeHub that a build can do it
  (older images keep one person at a time).

Nothing is sent outside the company.

To update: merge the upstream changes into the `officehub` branch of the forks, change the commits in the
`Dockerfile` and build the image.
