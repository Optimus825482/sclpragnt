# Taste

- Communicates in Turkish and expects responses in Turkish (frequently types in all caps). Confidence: 0.97
- Is pragmatic about running/operating the stack on their own machine — expecting the assistant to verify the Python environment (which libraries and versions are actually installed, what codecs/formats those versions accept) and to run the frontend typecheck/build locally as proof before handing back steps to apply on the deployed environment. Confidence: 0.7
- Wants the assistant to first inspect the existing system and give its own opinion/validation of proposed ideas before implementing ("önce mevcut sistemi incele, sonra değerlendir", "sen ne dersin?"; supplied a weakness/audit list and asked which items actually still need fixing). Confidence: 0.9
- Prefers progressing in small sequential stages with confirmation between each ("sonraki aşamayla devam edelim") rather than large one-shot changes. Confidence: 0.8
