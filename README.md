# vk-json

`vk.xml` (Vulkan registry) adapted into an object-oriented JSON: `vk.json` (pretty) and `vk.min.json`.

Regenerated daily by GitHub Actions from [KhronosGroup/Vulkan-Docs](https://github.com/KhronosGroup/Vulkan-Docs) (`UPSTREAM_COMMIT` holds the source SHA).

```
python3 convert.py --input vk.xml --output vk.json [--minify] [--commit SHA]
```

## Schema

Top-level keys: `meta`, `constants`, `enums`, `platforms`, `tags`, `types`, `commands`, `features`, `extensions`, `formats`, `spirvExtensions`, `spirvCapabilities`, `sync`, `videoCodecs`.

- Named collections are objects keyed by name; ordered lists (`members`, `params`, `require`) are arrays.
- Comma-separated attributes (`api`, `successCodes`, `len`, `optional`...) are arrays; `optional` holds booleans.
- C declarations are split into `type`, `const`, `pointer` (depth), `constPointer`, `array`, `bitfield`.
- Numeric attributes (`value`, `bitpos`, `offset`, `number`) are ints; C expressions stay strings.
- Aliases: `{ "alias": "Target" }`. Duplicate names (e.g. vulkan vs vulkansc) go into `variants`.
