// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
// Dedicated YUV material; shared layout/controls/danmaku are unchanged.
// Uses only the default framebuffer on the old Mali driver.
class HardwarePicture {
    GLuint program=0,buffer=0,textures[3]={};GLint position=-1,uv=-1;
    int w=0,h=0,tw=0,th=0,format=0;bool full=false,bt709=true;
    static GLuint shader(GLenum kind,const char*code){GLuint s=glCreateShader(kind);glShaderSource(s,1,&code,nullptr);glCompileShader(s);GLint ok=0;glGetShaderiv(s,GL_COMPILE_STATUS,&ok);if(!ok)throw 56;return s;}
public:
    HardwarePicture(){
        const char*vertex="attribute vec2 p;attribute vec2 u;uniform vec2 canvas;uniform float origin_y;varying vec2 v;void main(){gl_Position=vec4(p.x*2./canvas.x-1.,1.-(p.y-origin_y)*2./canvas.y,0.,1.);v=u;}";
        const char*fragment="precision mediump float;varying vec2 v;uniform sampler2D ytex;uniform sampler2D utex;uniform sampler2D vtex;uniform float nv12;uniform vec2 yrange;uniform vec4 coeff;uniform vec2 uvscale;uniform vec2 halftexel;void main(){vec2 q=v*uvscale;vec2 yp=clamp(q,halftexel,uvscale-halftexel);vec2 cp=clamp(q,halftexel*2.,uvscale-halftexel*2.);float y=(texture2D(ytex,yp).r-yrange.x)*yrange.y;vec4 uv=texture2D(utex,cp);float u=uv.r-.5;float cr=mix(texture2D(vtex,cp).r,uv.a,nv12)-.5;gl_FragColor=vec4(y+coeff.x*cr,y-coeff.y*u-coeff.z*cr,y+coeff.w*u,1.);}";
        auto a=shader(GL_VERTEX_SHADER,vertex),b=shader(GL_FRAGMENT_SHADER,fragment);program=glCreateProgram();glAttachShader(program,a);glAttachShader(program,b);glLinkProgram(program);glDeleteShader(a);glDeleteShader(b);GLint ok=0;glGetProgramiv(program,GL_LINK_STATUS,&ok);if(!ok)throw 56;
        position=glGetAttribLocation(program,"p");uv=glGetAttribLocation(program,"u");glGenBuffers(1,&buffer);glBindBuffer(GL_ARRAY_BUFFER,buffer);glBufferData(GL_ARRAY_BUFFER,24*sizeof(GLfloat),nullptr,GL_DYNAMIC_DRAW);glBindBuffer(GL_ARRAY_BUFFER,0);
        glGenTextures(3,textures);for(auto texture:textures){glBindTexture(GL_TEXTURE_2D,texture);unsigned char v=128;glTexImage2D(GL_TEXTURE_2D,0,GL_LUMINANCE,1,1,0,GL_LUMINANCE,GL_UNSIGNED_BYTE,&v);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);}
    }
    ~HardwarePicture(){glDeleteTextures(3,textures);glDeleteBuffers(1,&buffer);glDeleteProgram(program);}
    void clear(){if(w)glFinish();w=h=0;}
    void upload(const p011_hw::Frame&f){
        if(f.format!=1&&f.format!=2)throw 54;
        if(w)glFinish();bool allocate=w!=int(f.width)||h!=int(f.height)||format!=int(f.format);w=f.width;h=f.height;format=f.format;full=f.full_range;bt709=f.matrix;
        // Old Mali/DRM allocation workaround: align BOTH chroma planes to
        // 16 pixels, while retaining the exact picture size/aspect. Sampling
        // is clamped to valid texels, never the uninitialized padding.
        tw=(w+31)&~31;th=(h+31)&~31;
        glPixelStorei(GL_UNPACK_ALIGNMENT,1);unsigned offset=0;
        for(int plane=0;plane<(format==2?2:3);plane++){
            int pw=plane?w/2:w,ph=plane?h/2:h;GLenum type=plane&&format==2?GL_LUMINANCE_ALPHA:GL_LUMINANCE;
            glActiveTexture(GL_TEXTURE0+plane);glBindTexture(GL_TEXTURE_2D,textures[plane]);
            if(allocate)glTexImage2D(GL_TEXTURE_2D,0,type,plane?tw/2:tw,plane?th/2:th,0,type,GL_UNSIGNED_BYTE,nullptr);
            glTexSubImage2D(GL_TEXTURE_2D,0,0,0,pw,ph,type,GL_UNSIGNED_BYTE,f.pixels+offset);
            offset+=pw*ph*(type==GL_LUMINANCE_ALPHA?2:1);
        }
        glActiveTexture(GL_TEXTURE0);
    }
    void draw(const p011_player::Layout&layout,p011_player::Rect area,int aspect,int screen_w,int screen_h,double slide=0){
        if(!w||!h)return;double ratio=aspect==3?16./9:aspect==4?4./3:double(w)/h;
        double vw=area.w,vh=area.h;if(aspect!=2){double scale=aspect==1?std::max<double>(area.w/ratio,area.h):std::min<double>(area.w/ratio,area.h);vw=ratio*scale;vh=scale;}
        double x=area.x+(area.w-vw)/2,y=area.y+(area.h-vh)/2;GLfloat vertices[]={float(x),float(y),0,0,float(x+vw),float(y),1,0,float(x),float(y+vh),0,1,float(x),float(y+vh),0,1,float(x+vw),float(y),1,0,float(x+vw),float(y+vh),1,1};
        for(int i=0;i<6;i++){auto p=layout.physical({vertices[i*4],vertices[i*4+1]+slide});vertices[i*4]=p.x;vertices[i*4+1]=p.y;}
        auto a=layout.physical({area.x,area.y}),b=layout.physical({area.x+area.w,area.y+area.h});
        auto surface=p011_player::active_surface();auto clip=surface.clip(a,b,screen_w,screen_h);
        glDisable(GL_BLEND);glDisable(GL_DEPTH_TEST);glDisable(GL_CULL_FACE);glEnable(GL_SCISSOR_TEST);glScissor(clip.x,clip.y,clip.w,clip.h);
        glUseProgram(program);glUniform2f(glGetUniformLocation(program,"canvas"),surface.width(),surface.height());glUniform1f(glGetUniformLocation(program,"origin_y"),surface.top());for(int plane=0;plane<3;plane++){glActiveTexture(GL_TEXTURE0+plane);glBindTexture(GL_TEXTURE_2D,textures[plane]);}
        glUniform1i(glGetUniformLocation(program,"ytex"),0);glUniform1i(glGetUniformLocation(program,"utex"),1);glUniform1i(glGetUniformLocation(program,"vtex"),2);
        glUniform2f(glGetUniformLocation(program,"uvscale"),float(w)/tw,float(h)/th);glUniform2f(glGetUniformLocation(program,"halftexel"),.5f/tw,.5f/th);
        glUniform1f(glGetUniformLocation(program,"nv12"),format==2?1:0);glUniform2f(glGetUniformLocation(program,"yrange"),full?0:16./255,full?1:255./219);
        if(bt709)glUniform4f(glGetUniformLocation(program,"coeff"),full?1.5748:1.7927,full?.1873:.2132,full?.4681:.5329,full?1.8556:2.1124);
        else glUniform4f(glGetUniformLocation(program,"coeff"),full?1.402:1.596,full?.3441:.3918,full?.7141:.813,full?1.772:2.0172);
        glBindBuffer(GL_ARRAY_BUFFER,buffer);glBufferSubData(GL_ARRAY_BUFFER,0,sizeof(vertices),vertices);glEnableVertexAttribArray(position);glEnableVertexAttribArray(uv);glVertexAttribPointer(position,2,GL_FLOAT,GL_FALSE,4*sizeof(GLfloat),nullptr);glVertexAttribPointer(uv,2,GL_FLOAT,GL_FALSE,4*sizeof(GLfloat),(void*)(2*sizeof(GLfloat)));glDrawArrays(GL_TRIANGLES,0,6);
        glDisableVertexAttribArray(position);glDisableVertexAttribArray(uv);glBindBuffer(GL_ARRAY_BUFFER,0);glDisable(GL_SCISSOR_TEST);glActiveTexture(GL_TEXTURE0);glUseProgram(0);
    }
};
