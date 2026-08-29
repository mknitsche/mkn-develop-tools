# mkn-kern

The shared foundation the other packages build on.

Deliberately small. Anything that only one package needs belongs in that
package, not here — a shared layer that grows by accretion becomes the thing
nobody dares to change.

**What will not go in here:** a provider client, a database handle, or anything
that assumes the author's own infrastructure. See the principles in the
[repository README](../../README.md).
