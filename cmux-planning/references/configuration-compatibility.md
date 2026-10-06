Every newly initialized run records the creation-only boolean
`configuration_created_and_accepted` in `state.json`. It is true only when that invocation created a
missing shared configuration and the operator accepted the new default with `--accept-config`; it is
false when initialization used an existing configuration. It does not mean that planning initialization
migrated a shared configuration—migration remains the separate, explicit `agents_config.py migrate
--accept` operation described above. New runs never write the former
`configuration_created_or_migrated_and_accepted` key.

Durable runs that contain only the legacy key remain readable and resumable. Its recorded boolean is
used as the compatibility value without rewriting the run merely because it was read. A state containing
both names is accepted only when their boolean values match; conflicting values are rejected with an
error that requires the operator to make them agree before the run can continue.

That configuration-field compatibility does not authorize legacy run-artifact trust. A run created
before run-state schema 3 / artifact-manifest version 1 remains inspectable through `status` and
`context`, but every state-changing command and worker launch refuses it with guidance to obtain a
human decision to restart or to use a separately reviewed migration procedure. No automatic migration
or digest baseline is inferred from files already present in such a run.

