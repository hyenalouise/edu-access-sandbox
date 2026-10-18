# 06 Analytics

One dataset per business or analytical question, ready for the dashboard.

Empty until milestone 04 (Serve). The job holds disabled placeholders for
`01_answer_ap1` to `04_answer_ap4` (#144 to #147), each starting from the fact
gates it reads. Peer grouping and peer comparison have no tasks yet: #148 adds
them once #142 approves the rule, after the AP2 and AP3 gates (D-051). Dataset names stay deferred until the
analytical questions and output grains are approved. Files follow
`NN_<verb>_<object>.sql`, with checks in `90_validate_<object>.sql` (see [File
naming and layout](../../docs/architecture/overview.md#file-naming-and-layout)).
