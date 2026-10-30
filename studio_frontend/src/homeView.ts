export type HomeView = "senza" | "agent-team";

const HOME_VIEWS: readonly HomeView[] = ["senza", "agent-team"];

export function parseHomeView(hash: string): HomeView {
  const view = hash.replace(/^#/, "");
  return HOME_VIEWS.includes(view as HomeView) ? (view as HomeView) : "senza";
}

export function homeViewHash(view: HomeView): string {
  return `#${view}`;
}
