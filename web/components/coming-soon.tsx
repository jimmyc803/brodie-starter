import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

// Placeholder for routes that are not built yet. Shows the token so a link can be checked end to end.
export async function ComingSoon({
  title,
  params,
}: {
  title: string;
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <Badge variant="secondary">Coming soon</Badge>
        <CardTitle className="text-2xl">{title}</CardTitle>
      </CardHeader>
      <CardContent className="text-sm text-muted-foreground">
        Link token: <code className="break-all">{token}</code>
      </CardContent>
    </Card>
  );
}
