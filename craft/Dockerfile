# WordCraft and DeckCraft in the browser (both MIT OR Apache-2.0, https://github.com/storytold), built from the
# OfficeHub forks (branch "officehub"): a document opens from the portal, Save puts it back, and everyone edits
# together live through OfficeHub.
# The result is a few static files served by nginx: nothing runs on the server and nothing calls outside services.

# The WebAssembly is the same on every machine: build it once on the build machine, also for arm64 images.
FROM --platform=$BUILDPLATFORM rust:1.95-slim AS build
ARG TRUNK_VERSION=0.21.14
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates pkg-config \
    && rm -rf /var/lib/apt/lists/*
RUN rustup target add wasm32-unknown-unknown && cargo install trunk --version "$TRUNK_VERSION" --locked
WORKDIR /src
# Exact commits, so every build is the same reviewed code; each app on its own, so a change to one only rebuilds that
# app. collab.json tells OfficeHub that the build edits together.
ARG WORDCRAFT_REPO=https://github.com/LetsManu/wordcraft
ARG WORDCRAFT_COMMIT=173f4e65d491770163217eeb1b03b463a3aa417d
RUN git init -q wordcraft && git -C wordcraft fetch -q --depth 1 "$WORDCRAFT_REPO" "$WORDCRAFT_COMMIT" \
    && git -C wordcraft checkout -q FETCH_HEAD \
    && cd wordcraft/apps/wordcraft-web && trunk build --release && mkdir -p /out && cp -r ../../dist/web /out/wordcraft \
    && echo '{"together": true}' > /out/wordcraft/collab.json
ARG DECKCRAFT_REPO=https://github.com/LetsManu/deckcraft
ARG DECKCRAFT_COMMIT=50e06f7656cc7030bb912c4fa852294d431b021b
RUN git init -q deckcraft && git -C deckcraft fetch -q --depth 1 "$DECKCRAFT_REPO" "$DECKCRAFT_COMMIT" \
    && git -C deckcraft checkout -q FETCH_HEAD \
    && cd deckcraft/apps/deckcraft-web && trunk build --release && mkdir -p /out && cp -r ../../dist/web /out/deckcraft \
    && echo '{"together": true}' > /out/deckcraft/collab.json
# Their licences travel with the files
RUN for app in wordcraft deckcraft; do cp $app/LICENSE-MIT $app/LICENSE-APACHE $app/NOTICE /out/$app/; done

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /out /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD wget -q -O /dev/null http://127.0.0.1:8080/wordcraft/index.html || exit 1
