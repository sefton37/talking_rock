# The Play

The Play is Talking Rock's hierarchical knowledge system, managed by CAIRN.

## Structure

```
The Play
├── Acts (life chapters: Career, Health, Home, Learning)
│   ├── Scenes (projects within an Act)
│   │   ├── Beats (tasks/items within a Scene)
│   │   └── Notebook (markdown notes for the Scene)
│   └── Notebook (markdown notes for the Act)
└── Contacts (people linked to Acts/Scenes)
```

## Concepts

### Acts
Top-level life domains. Examples: "Career", "Health", "Side Projects", "Family".

Each Act can have:
- A markdown notebook for notes
- Child Scenes (projects)
- Associated repositories (for RIVA context)
- Linked contacts

### Scenes
Projects or ongoing efforts within an Act. Examples: "Job Search", "Learn Rust", "Kitchen Renovation".

Each Scene can have:
- A markdown notebook
- Child Beats (tasks)
- Kanban state (active, backlog, waiting, someday, done)
- Priority (user-set, 1-5)
- Due dates

### Beats
Individual tasks or items within a Scene. The atomic unit of work.

Beats have:
- Title and optional notes
- Kanban state
- Priority
- Due date
- "Waiting on" field (person/thing blocking progress)

### Notebooks
Markdown files attached to Acts and Scenes. Free-form notes, meeting logs, research, whatever you need.

## CAIRN's Role

CAIRN is the attention minder for The Play:

1. **Surfaces priorities** - Shows what needs attention without overwhelming
2. **Tracks activity** - Knows when you last touched each item
3. **Manages state** - Moves items through kanban states
4. **Filters through identity** - Uses the Coherence Kernel to reject distractions
5. **Never guilt-trips** - Surfaces options, doesn't judge

## Storage

The Play is stored in SQLite (`~/.local/share/reos/reos.db`) with tables:
- `the_play` - Acts, Scenes, Beats hierarchy
- `play_notebooks` - Markdown content
- `cairn_metadata` - Activity tracking, priorities, kanban states
- `contacts` - People linked to projects

## MCP Tools

CAIRN exposes 27 MCP tools for Play management:
- `cairn_play_*` - CRUD for Acts/Scenes/Beats
- `cairn_kb_*` - Notebook read/write with diff preview
- `cairn_surface_*` - Priority surfacing
- `cairn_contacts_*` - Contact management
- `cairn_calendar_*` - Thunderbird calendar integration

See `docs/cairn_architecture.md` for full tool documentation.
