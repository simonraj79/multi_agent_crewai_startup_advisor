# Evidence for the run-shell build

Everything under this directory is the artifact half of
[`../DEFINITION-OF-DONE.md`](../DEFINITION-OF-DONE.md): one subdirectory per
criterion group (`G1`–`G4`, `T1`, `T2`, `T3`, `S`, `R`, `RC`), holding the
screenshots, pasted test output, greps and measurements that each row of
`../VERDICT.md` names. A row is `PASS` only when its artifact is on disk at the
path the table cites and the named verifier — never the builder — has read it,
so a file here is not a record of the work, it *is* the check: a reader who has
not seen the build conversation must be able to open these and reach the same
verdict. Test results are pasted as text files with the command that produced
them at the top, for the same reason. PNGs live here rather than being
regenerated on demand because a screenshot that exists on one machine cannot
answer anything, which is why `.gitignore`'s global `*.png` rule carries an
explicit `!docs/run-shell/evidence/**/*.png` exception for this directory and
nowhere else in `docs/`.
