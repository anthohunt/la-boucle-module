# Privacy

The module collects no data for its author and sends nothing to a service run by its author. What it records (the worksite files: the objective, the operator's decisions word for word, the measures) stays in the worksite folder on your machine (`racine_chantiers`, default `~/.la-boucle/chantiers`), or on the SSH host you set yourself, until you delete it.

Data leaves that folder only through what you configure: the optional SSH host (`hote`), the optional quota statement (`releve_comptes`), the notification command (`notification`, off by default), and the agents you start through `agents.lanceur`, which send to their model provider what you give them.

Questions: anthony@ingevision.cloud.
