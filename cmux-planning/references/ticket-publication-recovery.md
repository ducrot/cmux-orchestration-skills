# Ticket staging and publication recovery

Status distinguishes publication not started, fully staged but not yet recorded, recorded and validated,
already moved but not recorded, and completed. Repeating explicit ticket approval adopts complete
unrecorded staging only after it validates against the reviewed proposal and approved spec; partial or
changed staging stops for inspection. If interruption happens after the atomic move but before the final
state write, rerunning `publish` validates the existing target against the approved spec, proposal,
ticket set, and staged artifact identities before completing state. If both staging and target exist,
identities differ, or the run is already complete, publication refuses to duplicate or partially
overwrite anything.
