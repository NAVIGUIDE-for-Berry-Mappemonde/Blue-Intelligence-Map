import ConsoleShell from "./audit/ConsoleShell";

/**
 * BatchHub — coquille Console unique (Lancer / Règles / Runs / Journal).
 * Une carte de lancement par mode, les mêmes onglets partout.
 */
export default function BatchHub(props) {
  return <ConsoleShell key={props.mode || "projects"} {...props} />;
}
