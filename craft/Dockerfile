# WordCraft, DeckCraft and GridCraft in the browser (all MIT OR Apache-2.0, https://github.com/storytold), built from
# the OfficeHub forks (branch "officehub"): a document opens from the portal, Save puts it back, and everyone edits
# together live through OfficeHub.
# The result is a few static files served by nginx: nothing runs on the server and nothing calls outside services.

# The WebAssembly is the same on every machine: build it once on the build machine, also for arm64 images.
FROM --platform=$BUILDPLATFORM rust:1.95-slim AS build
ARG TRUNK_VERSION=0.21.14
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates pkg-config brotli \
    && rm -rf /var/lib/apt/lists/*
RUN rustup target add wasm32-unknown-unknown && cargo install trunk --version "$TRUNK_VERSION" --locked
WORKDIR /src
# Built for size (whole-program optimisation): about a third smaller WebAssembly, which downloads and starts much
# faster, above all on phones. Only this image's build; the apps' own repositories keep their settings.
ENV CARGO_PROFILE_RELEASE_OPT_LEVEL=s \
    CARGO_PROFILE_RELEASE_LTO=fat \
    CARGO_PROFILE_RELEASE_CODEGEN_UNITS=1
# Exact commits, so every build is the same reviewed code; each app on its own, so a change to one only rebuilds that
# app. collab.json tells OfficeHub that the build edits together.
ARG WORDCRAFT_REPO=https://github.com/LetsManu/wordcraft
ARG WORDCRAFT_COMMIT=5da15a57e3424a86f93e6bae358ecc00e4b7be64
RUN git init -q wordcraft && git -C wordcraft fetch -q --depth 1 "$WORDCRAFT_REPO" "$WORDCRAFT_COMMIT" \
    && git -C wordcraft checkout -q FETCH_HEAD \
    && cd wordcraft/apps/wordcraft-web && trunk build --release && mkdir -p /out && cp -r ../../dist/web /out/wordcraft \
    && echo '{"together": true}' > /out/wordcraft/collab.json
ARG DECKCRAFT_REPO=https://github.com/LetsManu/deckcraft
ARG DECKCRAFT_COMMIT=1a21c2dcaf4735491f48ed4adde0fa075d5f01b2
RUN git init -q deckcraft && git -C deckcraft fetch -q --depth 1 "$DECKCRAFT_REPO" "$DECKCRAFT_COMMIT" \
    && git -C deckcraft checkout -q FETCH_HEAD \
    && cd deckcraft/apps/deckcraft-web && trunk build --release && mkdir -p /out && cp -r ../../dist/web /out/deckcraft \
    && echo '{"together": true}' > /out/deckcraft/collab.json
ARG GRIDCRAFT_REPO=https://github.com/LetsManu/gridcraft
ARG GRIDCRAFT_COMMIT=11916b0e4673e823992aeee797b23e90cbc0a0cd
RUN git init -q gridcraft && git -C gridcraft fetch -q --depth 1 "$GRIDCRAFT_REPO" "$GRIDCRAFT_COMMIT" \
    && git -C gridcraft checkout -q FETCH_HEAD \
    && cd gridcraft/apps/gridcraft-web && trunk build --release && mkdir -p /out && cp -r ../../dist/web /out/gridcraft \
    && echo '{"together": true}' > /out/gridcraft/collab.json
# Their licences travel with the files
RUN for app in wordcraft deckcraft gridcraft; do cp $app/LICENSE-MIT $app/LICENSE-APACHE $app/NOTICE /out/$app/; done
# Compressed ahead of time (Brotli about a fifth of the WebAssembly's size, gzip for older browsers), and a list of
# the large files, so the portal can fetch them ahead of time and opening a document is quick.
RUN cd /out && for app in wordcraft deckcraft gridcraft; do \
      for f in $app/*.wasm $app/*.js; do brotli -q 11 -w 24 -k "$f" && gzip -9 -k "$f"; done; \
      (cd $app && printf '{"files": [%s]}\n' "$(ls *.wasm *.js | sed 's/.*/"&"/' | paste -sd, -)" > assets.json); \
    done

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /out /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD wget -q -O /dev/null http://127.0.0.1:8080/wordcraft/index.html || exit 1
