# Sheet Music Photos

Real photos of real printed sheet music, free for any use, including training and selling
commercial optical music recognition (OMR).

OMR works well on clean scans. It struggles with the pictures people actually take: a
page bent in a binder, a lamp's shadow, a pencil mark, a second page at the edge of the
frame. This dataset collects exactly those pictures, of music printed by many publishers
over a century, so that OMR can be trained and tested on them.

## Goals

- **Real music.** Every page is a scan of a printed edition from a library, from 1833 to
  1929: songs, piano pieces, choral and band music, by many publishers.
- **Real-world challenges.** Contributors print the pages and photograph them with bent
  paper, different light, busy backgrounds, annotations and more.
- **Free to use.** Scans are public domain, photos and transcriptions are CC0. Anyone can
  use the data for any purpose, also commercially, without asking.
- **No synthetic data.** See the rule below.

## No synthetic data

Everything in this repository is real:

- Scans are scans of printed paper. No pages rendered by notation software, no
  generated or edited music.
- Photos are taken with a camera of a printed page. No rendered photos, no AI-generated
  or AI-edited images, no simulated distortions, no filters or retouching beyond what
  the phone does on its own.
- Transcriptions are checked by people against the page.

Generated and augmented data are easy to make in any quantity; real photos are not. That
is the point of this dataset.

## What's in a page

```
scans/<id>/
  page.pdf             the scanned page, cut unchanged out of the source PDF
  print.pdf            the page cleaned for printing: white paper, no scan margins, A4
  meta.json            source, title, publication, license
  reference.musicxml   homr's reading of the clean scan, not verified
  page.musicxml        a verified transcription, once someone has checked the page
  photos/              contributed photos and photos.json
```

A transcription needs what OMR benchmarks compare: notes, rests, chords and key
signatures. Lyrics, dynamics and other markings may be missing.

### Reference and verified transcriptions

`reference.musicxml` is what [homr](https://github.com/liebharc/homr) reads from the clean
scan, with the homr commit in `meta.json`. On clean scans homr gets most notes and rests
right, so the reference is a good starting point, but it is not the truth: scores against
it measure how much a photo changes the result compared with the clean page. Report them
separately from scores against verified pages.

Some references were corrected by hand after homr made a structural error, such as a
grand staff read as one staff, or clefs guessed for lines that don't print one. `meta.json`
marks these with `"kind": "homr-corrected"` and describes what was fixed. They are better
than plain homr output but not fully checked, so they don't count as verified.

A checked and corrected reference becomes `page.musicxml` and counts as verified.

## Pages from libraries

Most pages come from the [Internet Archive](https://archive.org/), from
collections of libraries and archives:

| Collection | Holder |
|---|---|
| `gaylordmusiclibrary` | Gaylord Music Library, Washington University in St. Louis |
| `uno-sheet-music` | University of Nebraska Omaha |
| `canadiansheetmusic` | Canadian sheet music |
| `uoftsheetmusic` | University of Toronto |
| `conncollsheetmusic` | Connecticut College |

A scan was used only if the holding library marked it with the
[Public Domain Mark](https://creativecommons.org/publicdomain/mark/1.0/) or
[CC0](https://creativecommons.org/publicdomain/zero/1.0/), and it was published in 1929
or earlier. Community uploads were left out, because no institution checked their rights.

How the pages were chosen:

1. The collections were searched once; the result is frozen in
   `sources/ia-candidates.json`.
2. Candidates were shuffled with a fixed seed within each collection and taken from the
   collections in turn.
3. From each scan one page was chosen at random among those with at least three staves,
   so covers and text pages were skipped.
4. homr transcribed each page. Pages where homr failed on a large scale were replaced: a
   one-staff part that changes clef more than twice, which happens with band parts that
   print the clef only on the first line. A few such pages were added back with a
   hand-corrected reference (`homr-corrected`), one for each kind of error.

`scans/attempted.json` lists every candidate that was tried: added, skipped (for example
"no PDF") or dropped with the reason. `make reproduce` downloads every source PDF again,
checks the SHA-1 the Internet Archive lists for it, cuts out the recorded page and
compares it byte for byte with `page.pdf`.

## Contributing

There are three ways to help. Each one is a pull request.

Set up once:

```bash
git clone <this repository> && cd sheet-music-photos
uv sync
```

### 1. Photos

1. Pick a page from `scans/`. Pages without a `photos/` folder need photos most.
2. Print `print.pdf` at 100% scale ("actual size") on A4, or "fit to page" on Letter.
3. Take 1 to 10 photos with your phone. Vary them the way real use varies:
   - put the page on a music stand
   - use diverse backgrounds and surfaces: a wooden table, a carpet, a bedsheet, a desk
     full of things
   - change the light: daylight, a lamp at night, dim light, a shadow of your hand or
     phone, glare from a window
   - lay it on a book or in a binder so that it bends and warps
   - put it next to another page from this repository, so that the other page is
     partly visible in the photo
   - add annotations: fingerings, circled notes, written-in note names, a crossed-out bar
   - fold, crumple or tilt it, or photograph it from an angle

   Every photo must stay usable: the whole page is visible, nothing covers the music
   (fingers, pens, the other page), and a musician could read every note and rest from
   the photo without having to guess. A photo where part of the music is cut off, hidden
   or too blurry to read can't be used.
4. Add the photos to the page. This removes location and device data from the files and
   scales them to 1920 px on the longer side:

   ```bash
   uv run python -m smp.photos scans/<id> --by "Your name or handle" \
       --conditions curved shadow IMG_1234.jpg IMG_1235.jpg
   ```

   Conditions describe what the photos show: `flat`, `stand`, `curved` (book or binder),
   `folded`, `crumpled`, `tilted`, `shadow`, `dim`, `glare`, `background` (busy surface),
   `neighbor` (another page partly visible), `annotated`, `other`.
5. Run `make check` and open a pull request with the new `scans/<id>/photos/` folder.

By adding photos you confirm that you took them yourself and dedicate them under CC0.
Please keep faces and other personal things out of the frame.

### 2. Ground truth

Turn a reference into a verified transcription:

1. Open `reference.musicxml` in a notation editor, for example MuseScore, next to
   `page.pdf`.
2. Go through the whole page and fix notes, rests, chords and key signatures until they
   match the print. Other markings can stay as they are.
3. Export the result as MusicXML to `page.musicxml` in the same folder.
4. Open a pull request. In its description, confirm that you checked the whole page and
   dedicate your correction under CC0.

### 3. Clean scans

Add a new page, which then becomes a starting point for photos and ground truth just like
the pages from libraries. The scan must be:

- of a printed edition published in 1929 or earlier, scanned by you or by an archive
  that marks it as public domain or CC0;
- complete and clean: the whole page, straight and readable;
- real: a scan of paper, not a page rendered by notation software (see the rule above).

Add it with its source and license:

```bash
uv run python -m smp.scan my-scan.pdf --page 2 --title "Song title" --published 1912 \
    --by "Your name or handle" --source "My own copy, Leo Feist, New York" --license CC0-1.0 \
    --confirm
```

`--confirm` records this statement with your name in `meta.json`, and `make check` rejects a
contributed scan without it:

> I confirm that this metadata is correct; that the page is a real scan of a printed
> edition published in 1929 or earlier, not rendered or generated; that I may share it
> under the license stated; and that any transcription I add was checked by me against
> the page and is dedicated under CC0 1.0.

Then create a reference with `make references HOMR=../homr` (needs a
[homr](https://github.com/liebharc/homr) checkout), or add a verified `page.musicxml`
yourself, run `make check` and open a pull request. For a scan from your own copy you
dedicate the scan under CC0; for an archive's scan, give its record URL with `--url` and
the license it states (`PDM-1.0` or `CC0-1.0`).

## Commands

| Command | |
|---|---|
| `make check` | check hashes, licenses and contributed photos |
| `make printable` | recreate every `print.pdf` from its `page.pdf` |
| `make references HOMR=../homr` | transcribe pages without a reference |
| `make quality` | list pages whose reference has large-scale errors and replace them |
| `make reproduce` | download the sources of the library pages again and compare every `page.pdf` |
| `make scans COUNT=n` | add the next n pages from the frozen candidate list |

## License

The code is under the MIT license (`LICENSE`). Scans are public domain or CC0 as stated in
their `meta.json`. Metadata, transcriptions, photos and documentation are CC0.
