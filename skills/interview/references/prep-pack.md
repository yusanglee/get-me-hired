---
name: prep-pack
description: How to build an interview prep pack from the materials actually submitted (reading them, STAR outlines, numbers to defend, questions to ask). Read when the interview skill builds a pack.
---

# Building the prep pack

The interviewer has the submitted versions of the resume, cover letter and posting, so prepare from those, not from
the current master resume.

1. `gmh tracker prep <id|key> --workspace <ws>` prints the inputs in the shape of
   [interview-prep.md](../../../templates/interview-prep.md): the paths of the submitted resume, cover letter and
   saved posting, and every number on the resume with its source line. (`gmh tracker materials <key>` lists the
   archived files, including `application-notes.md`.)
2. Read the submitted resume (the PDF's text), the cover letter, the saved posting and `application-notes.md`.
3. Fill the template and write `<folder>/interview-prep.md`:
   - **What they stress:** the role in two lines and what the posting stresses most, quoted.
   - **Your matching stories:** for each top requirement, the resume bullet that answers it and a STAR outline built
     only from that bullet and the master resume. A requirement with no supporting fact is marked as a gap to
     prepare for honestly. (Gaps belong here, for the user; never in anything an employer sees.)
   - **Numbers to know:** every number on the submitted resume, with its source line, so the user can defend it.
   - **Questions to ask:** tied to the posting.
   - **Logistics:** the interview stage, date and interviewers, only if the user gives them.
4. Facts come only from the submitted materials, the master resume and what the user says
   ([rules.md](../../../references/rules.md)). Show the user the path and the stories, and ask what to change.
