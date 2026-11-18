# Web

`apps/web` is the Spanish search page at <https://reclamos.rising.sh>. It is a
React client that Vite builds as static files. A Cloudflare Worker serves the
`dist` bundle as assets; `wrangler.jsonc` holds its configuration.

## Components

The page uses GitButler's design system. Two workspace packages hold a copy of
it from [gitbutlerapp/gitbutler](https://github.com/gitbutlerapp/gitbutler) at
commit `c5297ae8daa0d845eaa3e3d3ebac203517ea24a1`:

| Package                 | Upstream path           | Holds                                     |
| ----------------------- | ----------------------- | ----------------------------------------- |
| `packages/but-ui`       | `packages/but-ui`       | Tokens, fonts, reset and text classes     |
| `packages/but-ui-react` | `packages/but-ui-react` | React components, icons and illustrations |

Both packages are under the Functional Source License 1.1 with an MIT future
license (FSL-1.1-MIT). Each keeps its `LICENSE.md`. The rest of the repository
stays MIT.

The copy leaves out:

- the "But Head" display font, which the page does not use;
- the GitButler logos and the `Logo` component;
- the stories, the tests and the package scripts.

`fonts.css` loads only Inter and Geist Mono. `tokens.css` still names "But Head"
in `--but-font-family-accent`. Nothing on the page uses that token.

Each package's `DESIGN.md` and `design/` folder are the rules for using its
components. The page follows them: one `pop` button per surface, outcome badges
coloured by meaning, a `Banner` for a failed search and an `EmptyState` when no
case is close enough.

Import a component by its file, with the extension:

```ts
import { Button } from "@gitbutler/but-ui-react/Button.tsx";
```

`main.tsx` imports `@gitbutler/but-ui/core` and
`@gitbutler/but-ui-react/base.css` once. `index.html` sets
`data-but-density="spacious"` for 2rem controls and `data-hand-cursor` for the
pointer cursor on buttons.

The page's own styles are CSS modules next to each component. They use the
`--but-*` tokens, so the page follows the system's light and dark schemes.

## Bundle size

`icons.ts` loads every icon eagerly through `import.meta.glob`. About 137 KB of
the 566 KB script is SVG text the page never shows. The script is 172 KB after
gzip. Change `icons.ts` upstream before trimming it here, so a resync does not
undo the change.

## Resync

1. Clone GitButler at the new commit.
2. Copy `packages/but-ui` and `packages/but-ui-react` over the local packages.
3. Remove the parts listed above.
4. Keep the local `package.json` of each package. Copy a new runtime dependency
   from the upstream `package.json` into it.
5. Update the commit in this page and run `mise run check`.
