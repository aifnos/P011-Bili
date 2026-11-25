/* Finite P011 SDL/GLES ABI probe. No files, network, or vendor process changes. */
#include <stdio.h>
#include <signal.h>
#include <unistd.h>
#include <SDL.h>
#include <GLES2/gl2.h>

int main(void) {
    alarm(10);
    if (SDL_Init(SDL_INIT_VIDEO) != 0) { fprintf(stderr,"SDL_INIT: %s\n",SDL_GetError()); return 2; }
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK, SDL_GL_CONTEXT_PROFILE_ES);
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION, 2);
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION, 0);
    SDL_GL_SetAttribute(SDL_GL_DOUBLEBUFFER, 1);
    SDL_Window *window = SDL_CreateWindow("P011 Bili graphics probe", SDL_WINDOWPOS_UNDEFINED, SDL_WINDOWPOS_UNDEFINED, 800, 480, SDL_WINDOW_OPENGL | SDL_WINDOW_SHOWN | SDL_WINDOW_FULLSCREEN_DESKTOP | SDL_WINDOW_BORDERLESS | SDL_WINDOW_RESIZABLE);
    if (!window) { fprintf(stderr,"SDL_WINDOW: %s\n",SDL_GetError()); SDL_Quit(); return 3; }
    SDL_GLContext context = SDL_GL_CreateContext(window);
    if (!context) { fprintf(stderr,"SDL_GL: %s\n",SDL_GetError()); SDL_DestroyWindow(window); SDL_Quit(); return 4; }
    int w=0,h=0;SDL_GL_GetDrawableSize(window,&w,&h);
    printf("GL_VERSION=%s\nGL_RENDERER=%s\nDRAWABLE=%dx%d\n",glGetString(GL_VERSION),glGetString(GL_RENDERER),w,h);
    fflush(stdout);
    for(int frame=0;frame<90;frame++) {
        SDL_Event e; while(SDL_PollEvent(&e)) { if(e.type==SDL_QUIT)frame=90; }
        SDL_GL_GetDrawableSize(window,&w,&h);
        glViewport(0,0,w,h);glDisable(GL_SCISSOR_TEST);glClearColor(0.055f,0.055f,0.055f,1);glClear(GL_COLOR_BUFFER_BIT);
        glEnable(GL_SCISSOR_TEST);glScissor(150,106,500,268);glClearColor(0.07f,0.65f,0.48f,1);glClear(GL_COLOR_BUFFER_BIT);glDisable(GL_SCISSOR_TEST);
        SDL_GL_SwapWindow(window);SDL_Delay(20);
    }
    GLenum error=glGetError();printf("FINAL_DRAWABLE=%dx%d\nGL_ERROR=%u\n",w,h,(unsigned)error);
    SDL_GL_DeleteContext(context);SDL_DestroyWindow(window);SDL_Quit();
    puts("OWN_WINDOW_CLOSED");return error ? 5 : 0;
}
