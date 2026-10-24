import React from "react";
import { MyComposition } from "./Composition";

const fontStyles = `
@import url('https://fonts.googleapis.com/css2?family=Montserrat:ital,wght@0,800;0,900;1,800;1,900&display=swap');
`;

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: fontStyles }} />
      <MyComposition />
    </>
  );
};
