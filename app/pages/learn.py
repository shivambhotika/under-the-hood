from __future__ import annotations

import streamlit as st

from app.components import empty_state
from app.data_loader import db_has_data


def render() -> None:
    if not db_has_data():
        st.title("How to Read This")
        empty_state()
        return

    st.title("How to Read This")
    st.caption("Under The Hood in plain English - no technical background required.")

    st.markdown(
        """
### What is this?
Under The Hood scans thousands of real software projects on GitHub and
looks at what tools they have installed. Not what developers say they use.
Not what's trending on Twitter. What's literally in their code.

Think of it like a supermarket scanner for software. Instead of checking
what people say they're buying, we look at what's actually in their cart.
"""
    )

    st.markdown("### The key concepts")

    with st.expander("What is a 'repo' or 'repository'?"):
        st.markdown(
            """
A repository is a project on GitHub - a collection of code, usually
for one piece of software. "8,102 repos use Vitest" means 8,102
separate software projects have Vitest installed.

We only track repos with 500+ GitHub stars. Stars are roughly like
likes - they indicate that other developers found the project
interesting or useful. 500+ stars filters out hobby projects and
abandoned experiments, leaving us with serious, maintained software.
"""
        )

    with st.expander("What is a 'dependency'?"):
        st.markdown(
            """
When developers build software, they don't write everything from scratch.
They use pre-built tools - called dependencies or packages - that handle
common tasks. A dependency file (like package.json or requirements.txt)
is a list of all the tools a project is using.

When we say "scanning dependencies", we mean: reading these lists across
thousands of projects to see which tools appear most often.
"""
        )

    with st.expander("What is 'adoption' and how is it different from popularity?"):
        st.markdown(
            """
Popularity = how many people have heard of something or talk about it.
Adoption = how many people are actually using it in real projects.

These can be very different. A tool can be popular on Twitter but rarely
used in real code (hype). Or a tool can be widely adopted but rarely
discussed (infrastructure). We measure adoption - what's in the code,
not what's in the conversation.
"""
        )

    with st.expander("What is the 'Emergence Score'?"):
        st.markdown(
            """
A tool with 200 projects and growing 40% in 90 days is more interesting
than a tool with 15,000 projects growing 2%. The emergence score captures
this - it rewards growth relative to size, not absolute size.

High emergence = growing fast from a smaller base. This is often an
early signal before a tool becomes mainstream.

Low emergence + high adoption = established infrastructure. Think pytest
for Python - everyone uses it, it's not growing fast, and that's fine.
"""
        )

    with st.expander("What does 'market phase' mean?"):
        st.markdown(
            """
We categorize each tool category by its competitive dynamics:

Early / Competing - Many tools exist, none clearly winning.
Like smartphones in 2006 - lots of options, no settled standard yet.

Consolidating - A winner is pulling ahead but hasn't won yet.
Like the browser wars in the late 2000s - Chrome was winning but IE still had users.

Mature - One tool has effectively won.
Like Google for search - technically there are alternatives but almost no one uses them.

Fragmenting - Many tools, none gaining momentum.
Sometimes means the problem is unsolved; sometimes means developers prefer to build their own.
"""
        )

    with st.expander("What does this NOT tell you?"):
        st.markdown(
            """
Important limitations to understand:

- We only see public code. Most enterprise software is private - we
  cannot measure how banks, hospitals, or large companies build software.

- Being in a dependency file does not equal actively used. A tool might be installed
  but unused. We cannot tell from the outside.

- 500+ star filter means we miss new tools before they become popular.
  We deliberately trade coverage for quality.

- This is not a survey of developer preferences. We measure what is
  installed in code, which is correlated with but not identical to
  what developers would recommend.
"""
        )

    st.markdown(
        """
### Who is this for?
Originally built with two audiences in mind:

For developers: A way to see what the ecosystem is actually adopting -
useful when choosing between tools or doing due diligence on a dependency.

For investors and analysts: Open-source adoption is often a leading
indicator of a technology category's direction. The tool winning in OSS
today tends to be the tool enterprises pay for tomorrow.
(Kubernetes, Elasticsearch, Redis - all followed this pattern.)

For the curious: The OSS ecosystem moves fast. This is a window into
what the engineering world is building right now - without needing to
read thousands of GitHub repos yourself.
"""
    )
