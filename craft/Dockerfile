# WordCraft and DeckCraft in the browser (both MIT OR Apache-2.0, https://github.com/storytold), built from their
# source with OfficeHub's small patch so a document opens from the portal and Save puts it back (patches/).
# The result is a few static files served by nginx: nothing runs on the server and nothing calls outside services.

# The WebAssembly is the same on every machine: build it once on the build machine, also for arm64 images.
FROM --platform=$BUILDPLATFORM rust:1.95-slim AS build
ARG WORDCRAFT_COMMIT=e05b7fe86f3b85454000dffc321de638d7009817
ARG DECKCRAFT_COMMIT=63831cdfa9e13ad503d18e6ee210767919352128
ARG TRUNK_VERSION=0.21.14
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates pkg-config \
    && rm -rf /var/lib/apt/lists/*
RUN rustup target add wasm32-unknown-unknown && cargo install trunk --version "$TRUNK_VERSION" --locked
COPY patches/ /patches/
WORKDIR /src
# Exact commits, so every build is the same reviewed code
RUN for app in wordcraft:$WORDCRAFT_COMMIT deckcraft:$DECKCRAFT_COMMIT; do \
      name=${app%%:*}; commit=${app#*:}; \
      git init -q $name && git -C $name fetch -q --depth 1 https://github.com/storytold/$name "$commit" \
      && git -C $name checkout -q FETCH_HEAD && git -C $name apply /patches/$name-web.patch || exit 1; \
    done
RUN cd wordcraft/apps/wordcraft-web && trunk build --release && mkdir -p /out && cp -r ../../dist/web /out/wordcraft
RUN cd deckcraft/apps/deckcraft-web && trunk build --release && cp -r ../../dist/web /out/deckcraft
# Their licences travel with the files
RUN for app in wordcraft deckcraft; do cp $app/LICENSE-MIT $app/LICENSE-APACHE $app/NOTICE /out/$app/; done

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /out /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD wget -q -O /dev/null http://127.0.0.1:8080/wordcraft/index.html || exit 1
